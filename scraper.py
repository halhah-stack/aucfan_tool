"""
scraper.py — AucFan Selenium スクレイパー

【役割】
  - 既存の Chrome（リモートデバッグポート 9222）に接続してスクレイピングを実行
  - AucFanScraper クラスが STEP 1 / STEP 2 / STEP 3 で共通して使われる基底クラス
  - SellerAnalyzer（seller_analyzer.py）はこのクラスを継承してセラー分析に特化

【スクレイピングフロー（STEP 1 キーワードリサーチ）】
  1. _scrape_list_pages  : 一覧ページを全ページ取得（50件/ページ）
  2. _run_phash_grouping : pHash 画像類似度でグループ化（中間）
  3. _scrape_detail_pages: 候補商品の詳細ページ取得（送料・サイズ情報取得）
  4. _run_phash_grouping : 最終グループ化（詳細取得後に再実行）
  5. _run_vision_group_check: Gemini Vision API による画像・タイトル判定

【主な設定値（config.py で変更可能）】
  MIN_DELAY / MAX_DELAY    : ページ取得間のランダム待機時間（サーバー負荷対策）
  MAX_PAGES                : 最大取得ページ数（デフォルト 500）
  MIN_PRICE / MAX_PRICE    : 一覧取得時の価格フィルター（skip_price_filter=True で無効化）
  PHASH_THRESHOLD          : pHash 類似度の閾値（数値が大きいほど緩い判定）
  CHROME_DEBUG_HOST/PORT   : Chrome デバッグ接続先（デフォルト 127.0.0.1:9222）

【停止・再開】
  stop_event.set() で各ループが停止シグナルを検出して安全に終了する。
  再開時（resume=True）は DataManager.load_previous_session() で前回データを引き継ぐ。
"""
import hashlib
import logging
import random
import re
import time
import threading
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException
)

import config
from data_manager import DataManager
from image_processor import ImageProcessor
from gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class AucFanScraper:
    """
    AucFan スクレイパー本体。
    既存の Chrome ブラウザに接続してスクレイピングを行う。
    """

    def __init__(
        self,
        data_manager: DataManager,
        image_processor: ImageProcessor,
        gemini_client: GeminiClient,
        stop_event: threading.Event,
    ):
        self.dm = data_manager
        self.img = image_processor
        self.gemini = gemini_client
        self.stop_event = stop_event
        self.driver: Optional[webdriver.Chrome] = None
        # 価格フィルターを適用するかどうか
        #   False（デフォルト）: MIN_PRICE 〜 MAX_PRICE*1.5 の範囲外を除外
        #   True              : セラー分析で全商品を取得するために SellerAnalyzer.__init__ で True に設定
        self.skip_price_filter: bool = False
        # アプリ画面「X件中Y件処理済み」表示用カウンター
        self._total_items: int = 0      # スクレイピング対象の総件数（詳細取得フェーズで確定）
        self._processed_items: int = 0  # 処理済み件数（UI の進捗カウンターに反映）

    # ─────────────────────────────────────────────
    # Chrome 接続
    # ─────────────────────────────────────────────

    def connect_to_chrome(self) -> bool:
        """
        既存の Chrome（リモートデバッグモード）に接続する。
        戻り値: 接続成功なら True
        """
        try:
            options = Options()
            options.add_experimental_option(
                "debuggerAddress",
                f"{config.CHROME_DEBUG_HOST}:{config.CHROME_DEBUG_PORT}"
            )
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")

            self.driver = webdriver.Chrome(options=options)
            logger.info(f"Chrome に接続しました（初期タブ）: {self.driver.current_url}")

            # AucFanタブに切り替え（見つからない場合は現在のタブで続行）
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                current = self.driver.current_url
                if "aucfan.com" in current:
                    logger.info(f"AucFanタブに切り替えました: {current}")
                    break
            else:
                # セラー分析では直後に navigate() で目的のURLへ移動するため問題なし
                logger.info(
                    "AucFanタブが見つかりません（スクレイピング開始時に移動します）: "
                    + self.driver.current_url
                )

            logger.info(f"現在のURL: {self.driver.current_url}")
            return True

        except WebDriverException as e:
            logger.error(
                f"Chrome への接続に失敗しました。\n"
                f"  エラー: {e}\n"
                f"  Chrome がリモートデバッグモードで起動しているか確認してください。\n"
                f"  起動方法: bash launch_chrome.sh"
            )
            return False
        except Exception as e:
            logger.error(f"予期しないエラー: {e}")
            return False

    def disconnect(self):
        """ドライバーを閉じる（ブラウザは閉じない）"""
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self.driver = None

    # ─────────────────────────────────────────────
    # メインスクレイプフロー
    # ─────────────────────────────────────────────

    def run(self, resume: bool = False, start_url: Optional[str] = None):
        """
        スクレイピングのメインフロー。
        start_url が指定された場合はそのURLに遷移してからスクレイプ開始。
        Step1: 一覧ページ → Step2: 詳細ページ（候補のみ）
        """
        logger.info("=== AucFan スクレイピング開始 ===")

        if not self.connect_to_chrome():
            self.dm.update_progress(status="error")
            return

        try:
            # start_url が指定されていれば新規タブを開いてそこへ遷移
            if start_url:
                logger.info(f"新規タブでAucFanを開きます: {start_url}")
                self.driver.execute_script("window.open('about:blank', '_blank');")
                self.driver.switch_to.window(self.driver.window_handles[-1])
                self.driver.get(start_url)
                WebDriverWait(self.driver, config.PAGE_LOAD_TIMEOUT).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
                logger.info(f"タブ遷移完了: {self.driver.current_url}")

            # 現在のURLとキーワードを取得
            current_url = self.driver.current_url
            keyword = self._extract_keyword_from_url(current_url)
            logger.info(f"現在のURL: {current_url}")
            logger.info(f"キーワード: {keyword or '（取得できず）'}")

            self.dm.update_progress(
                status="scraping_list",
                current_url=current_url,
                keyword=keyword or "unknown",
            )

            # Step1: 一覧ページ取得
            if not self.stop_event.is_set():
                logger.info("=== Step1: 一覧ページ取得 ===")
                self._scrape_list_pages(current_url, resume=resume)

            # pHashグループ化（中間）
            if not self.stop_event.is_set():
                logger.info("=== pHashグループ化（中間）===")
                self.dm.update_progress(status="grouping")
                self._run_phash_grouping()

            # Step2: 候補商品の詳細ページ取得
            if not self.stop_event.is_set():
                logger.info("=== Step2: 詳細ページ取得 ===")
                self.dm.update_progress(status="scraping_detail")
                self._scrape_detail_pages()

            # 最終グループ化・候補昇格
            if not self.stop_event.is_set():
                logger.info("=== 最終グループ化 ===")
                self._run_phash_grouping()

            # Vision判定（最終グループ化後）
            if not self.stop_event.is_set():
                self.dm.update_progress(status="vision_check")
                self._run_vision_group_check()

            final_status = "stopped" if self.stop_event.is_set() else "done"
            self.dm.update_progress(status=final_status)
            logger.info("=" * 50)
            logger.info(f"=== STEP 1 スクレイピング完了 === 全{self.dm.total_items}件処理 ({final_status})")
            logger.info("=" * 50)
            logger.info(">>> 待機中 (アプリは起動中) <<<  次の操作をブラウザから行ってください")

            # ── マスターセラーリストへ seller_id を追記 ──
            # group_size >= MASTER_SELLER_MIN_GROUP_SIZE のグループに属するセラーのみ対象
            try:
                from sellers_master import SellersMaster
                keyword = self.dm.get_progress().get("keyword", "")
                min_gs = config.MASTER_SELLER_MIN_GROUP_SIZE
                all_items = self.dm.get_all_items()
                all_sids_total = {
                    str(i.get("seller_id", "")).strip()
                    for i in all_items
                    if i.get("seller_id")
                }
                # group_size >= min_gs のアイテムに絞る
                qualified_sids = list({
                    str(i.get("seller_id", "")).strip()
                    for i in all_items
                    if i.get("seller_id")
                    and int(i.get("group_size") or 1) >= min_gs
                })
                if qualified_sids:
                    added = SellersMaster().upsert_sellers(qualified_sids, source_keyword=keyword)
                    logger.info(
                        f"マスターリストに{added}件追加"
                        f"（グループ{min_gs}件以上セラー{len(qualified_sids)}件"
                        f" / 全セラー{len(all_sids_total)}件中）"
                    )
                else:
                    logger.info(
                        f"マスターリスト追加対象なし"
                        f"（グループ{min_gs}件以上のセラーが存在しない / 全セラー{len(all_sids_total)}件）"
                    )
            except Exception as _e:
                logger.warning(f"sellers_master 更新スキップ: {_e}")

        except Exception as e:
            logger.error(f"スクレイピング中に予期しないエラー: {e}", exc_info=True)
            self.dm.update_progress(status="error")
            self.dm.add_error(str(e))
        finally:
            self.dm.save_all()
            # ドライバーを閉じる（ブラウザは閉じない）
            try:
                if self.driver:
                    # detach してからquit（ブラウザを残す）
                    self.driver.quit()
            except Exception:
                pass

    # ─────────────────────────────────────────────
    # Step1: 一覧ページ取得
    # ─────────────────────────────────────────────

    def _scrape_list_pages(self, start_url: str, resume: bool = False):
        """
        一覧ページを順にスクレイプする。
        """
        progress = self.dm.get_progress()
        start_page = 1

        if resume and progress.get("pages_done", 0) > 0:
            # 再開: 最後のページの次から
            start_page = progress["pages_done"] + 1
            logger.info(f"再開: {start_page}ページ目から")

        current_url = start_url

        # start_page > 1 の場合はそのページへ移動
        if start_page > 1:
            current_url = self._build_page_url(start_url, start_page)
            self._navigate(current_url)

        page = start_page
        consecutive_errors = 0

        while page <= config.MAX_PAGES and not self.stop_event.is_set():
            logger.info(f"[一覧] ページ {page}: {current_url}")

            try:
                # ── 商品取得（リトライあり）──
                items, all_timed_out = self._fetch_page_items_with_retry(
                    current_url, max_retries=2
                )

                if not items:
                    if all_timed_out:
                        # 全リトライがタイムアウト → ページ読み込み失敗扱いでスキップ
                        logger.warning(f"[一覧] ページ {page}: 全リトライタイムアウト → スキップ")
                        # consecutive_errors はカウントしない
                    else:
                        logger.info(f"[一覧] ページ {page}: リトライ後も商品なし")
                        consecutive_errors += 1
                        if consecutive_errors >= 3:
                            logger.info("連続3ページ空白のため一覧取得を終了します")
                            break
                else:
                    prev_count = self.dm.total_items
                    for item in items:
                        self.dm.add_item(item)
                    new_count = self.dm.total_items - prev_count

                    if new_count == 0:
                        # 全件が重複 = 同一ページを再取得している（ページネーション終了）
                        logger.info(
                            f"[一覧] ページ {page}: {len(items)}件取得したが全て重複。"
                            "ページネーション終了と判定。"
                        )
                        break

                    consecutive_errors = 0
                    self._processed_items = self.dm.total_items
                    logger.info(
                        f"[一覧] ページ {page}: {len(items)}件取得"
                        f" (新規: {new_count}件, 累計: {self.dm.total_items}件)"
                    )
                    self.dm.update_progress(
                        pages_done=page,
                        total_items=self.dm.total_items,
                        processed_items=self._processed_items,
                    )

                # 定期保存（10ページごと）
                if page % 10 == 0:
                    self.dm.save_all()

                # 次のページへ
                next_url = self._get_next_page_url(current_url, page)
                if not next_url:
                    logger.info("[一覧] 次のページが見つかりません。一覧取得完了。")
                    break

                current_url = next_url
                page += 1
                self._random_wait()

                # ページ遷移
                if not self._navigate(current_url):
                    consecutive_errors += 1
                    if consecutive_errors >= 5:
                        break

            except Exception as e:
                logger.warning(f"[一覧] ページ {page} でエラー: {e}")
                self.dm.add_error(f"ページ{page}: {e}")
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    logger.error("連続5回エラーのため一覧取得を終了します")
                    break
                self._random_wait()
                continue

        logger.info(f"一覧ページ取得完了: {self.dm.total_items}件")
        self.dm.save_all()

    # ─────────────────────────────────────────────
    # ページ取得（リトライあり）
    # ─────────────────────────────────────────────

    def _fetch_page_items_with_retry(
        self, url: str, max_retries: int = 2
    ) -> tuple:
        """
        現在ページの商品を取得する。0件またはタイムアウトの場合は
        ページをリロードして最大 max_retries 回リトライする。

        Returns:
            (items: List[dict], all_timed_out: bool)
              items が空 + all_timed_out=True  → 全試行がタイムアウト（スキップ推奨）
              items が空 + all_timed_out=False → リトライ後も確認済み空ページ
              items 非空                       → 取得成功
        """
        all_timed_out = True

        for attempt in range(max_retries + 1):  # 0, 1, 2
            if attempt > 0:
                wait_sec = random.uniform(2.0, 3.0)
                logger.info(
                    f"  [リトライ {attempt}/{max_retries}]"
                    f" リロード (待機 {wait_sec:.1f}秒) ..."
                )
                time.sleep(wait_sec)
                try:
                    self.driver.refresh()
                except Exception as e:
                    logger.warning(f"  リロード失敗: {e}")
                    continue  # all_timed_out は True のまま

            content_status = self._wait_for_page_content(timeout=15)

            if content_status == "timeout":
                logger.warning(
                    f"  読み込みタイムアウト"
                    f" (試行 {attempt + 1}/{max_retries + 1})"
                )
                continue  # all_timed_out は True のまま

            # "items" または "empty" → DOM は確定している
            all_timed_out = False
            items = self._parse_list_page()

            if items:
                if attempt > 0:
                    logger.info(f"  リトライ成功: {len(items)}件取得")
                return (items, False)

            # 0件
            if content_status == "empty":
                logger.info(
                    f"  商品なし確認"
                    f" (試行 {attempt + 1}/{max_retries + 1})"
                )
            else:
                logger.warning(
                    f"  0件（DOM確認済み）"
                    f" (試行 {attempt + 1}/{max_retries + 1})"
                )
            # 次のリトライへ

        return ([], all_timed_out)

    # ─────────────────────────────────────────────
    # ページコンテンツ待機
    # ─────────────────────────────────────────────

    def _wait_for_page_content(self, timeout: int = 15) -> str:
        """
        商品カードのDOMが出現するまで待機する。

        readyState=complete だけでは JS レンダリングが完了していない場合があるため、
        実際の商品カードセレクタが出現するまで最大 timeout 秒待つ。

        Returns:
            "items"   : 商品カードDOM検出（正常）
            "empty"   : AucFanの「商品がありません」ページを確認
            "timeout" : タイムアウト（DOM未確定）→ 呼び出し元でスキップ処理すること
        """
        # まず readyState=complete を待つ
        try:
            WebDriverWait(self.driver, config.PAGE_LOAD_TIMEOUT).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            return "timeout"

        # 商品カードセレクタが出現するまで最大 timeout 秒待つ
        card_selectors = config.SELECTORS["list"]["item_cards"]
        css = ", ".join(card_selectors)
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css))
            )
            return "items"
        except TimeoutException:
            pass

        # タイムアウト後: AucFanの「商品なし」状態かどうかを確認
        try:
            if self._detect_empty_page(self.driver.page_source):
                return "empty"
        except Exception:
            pass

        return "timeout"

    # AucFanが「商品がありません」を表示するときの典型的なテキストパターン
    _EMPTY_PAGE_PATTERNS = [
        "商品がありません",
        "見つかりませんでした",
        "一致する商品は見つかりませんでした",
        "検索条件に一致する商品はありませんでした",
    ]

    def _detect_empty_page(self, html: str) -> bool:
        """AucFanの「商品がありません」ページを検出する"""
        for pattern in self._EMPTY_PAGE_PATTERNS:
            if pattern in html:
                return True
        return False

    def _scroll_to_load_images(self):
        """
        ページを少しずつスクロールして遅延読み込み画像を全て発火させる。
        AucFanはビューポートに入ったときに data-src-original を src に変換する。
        """
        try:
            total_height = self.driver.execute_script("return document.body.scrollHeight")
            scroll_step = 600  # 1回あたりのスクロール量(px)
            current = 0
            while current < total_height:
                self.driver.execute_script(f"window.scrollTo(0, {current});")
                time.sleep(0.15)
                current += scroll_step
            # ページ最下部まで到達後、先頭に戻す
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.3)
        except Exception as e:
            logger.debug(f"スクロール中エラー（無視）: {e}")

    # 診断用: 「0件」が何件発生したか（HTMLダンプは最初の3件のみ）
    _zero_item_dump_count = 0
    _ZERO_ITEM_DUMP_MAX = 3

    def _parse_list_page(self) -> List[dict]:
        """現在のページをパースして商品リストを返す"""
        try:
            # ページ読み込み完了を待つ
            WebDriverWait(self.driver, config.PAGE_LOAD_TIMEOUT).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            # 遅延読み込み画像を全て発火させるためスクロール
            self._scroll_to_load_images()
            html = self.driver.page_source
        except Exception as e:
            logger.warning(f"ページソース取得エラー (条件C): {e}")
            return []

        soup = BeautifulSoup(html, "lxml")
        items = []
        current_url = ""
        try:
            current_url = self.driver.current_url
        except Exception:
            pass

        # 商品カードを探す（複数セレクターを試す）
        cards = self._find_elements_soup(soup, config.SELECTORS["list"]["item_cards"])

        if not cards:
            # ── 診断ログ: 条件A（セレクター不一致）──
            # どんな section タグがあるか / ページのサイズも記録
            sections = soup.find_all("section")
            section_classes = [
                " ".join(s.get("class", [])) for s in sections[:10]
            ]
            logger.warning(
                f"[診断 条件A] 商品カードセレクター不一致 URL={current_url}"
                f" | HTMLサイズ={len(html)}文字"
                f" | section数={len(sections)}"
                f" | sectionクラス={section_classes}"
            )
            self._dump_html_on_zero(current_url, html, "条件A_セレクター不一致")
            return []

        keyword = self._extract_keyword_from_url(current_url)

        # カードごとにパースしてフィルタ理由を集計
        filtered_no_title = 0
        filtered_price = 0
        for card in cards:
            try:
                item, reject_reason = self._parse_item_card_debug(card, keyword, current_url)
                if item:
                    items.append(item)
                elif reject_reason == "no_title":
                    filtered_no_title += 1
                elif reject_reason == "price":
                    filtered_price += 1
            except Exception as e:
                logger.debug(f"カードパースエラー: {e}")
                continue

        if not items and cards:
            # ── 診断ログ: 条件B（カードはあるが全フィルタアウト）──
            logger.warning(
                f"[診断 条件B] カード{len(cards)}枚あるが全フィルタアウト"
                f" | タイトル空={filtered_no_title}"
                f" | 価格フィルタ={filtered_price}"
                f" | URL={current_url}"
            )
            self._dump_html_on_zero(current_url, html, "条件B_全フィルタアウト")

        return items

    def _dump_html_on_zero(self, url: str, html: str, reason: str):
        """
        0件原因の診断用に HTML の先頭部分をファイルに保存する。
        最初の _ZERO_ITEM_DUMP_MAX 件のみ保存（ディスク節約）。
        """
        if self._zero_item_dump_count >= self._ZERO_ITEM_DUMP_MAX:
            return
        try:
            dump_dir = self.img.images_dir.parent / "debug_html"
            dump_dir.mkdir(exist_ok=True)
            fname = f"zero_items_{self._zero_item_dump_count + 1}_{reason[:30]}.html"
            fpath = dump_dir / fname
            # 先頭 50KB のみ保存
            fpath.write_text(html[:50_000], encoding="utf-8")
            logger.info(f"[診断] HTML保存: {fpath}  (URL={url})")
            self.__class__._zero_item_dump_count += 1
        except Exception as e:
            logger.debug(f"HTML保存失敗: {e}")

    def _parse_item_card_debug(
        self, card, keyword: str, base_url: str
    ) -> tuple:
        """
        _parse_item_card の診断版。フィルタ理由も返す。
        Returns: (item_dict | None, reject_reason: str)
          reject_reason: "" | "no_title" | "price"
        """
        item = self._parse_item_card(card, keyword, base_url)
        if item is not None:
            return (item, "")

        # どの条件で弾かれたか判定
        title_el = self._find_element_soup(card, config.SELECTORS["list"]["title"])
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return (None, "no_title")

        # タイトルはあるが None → 価格フィルタ
        return (None, "price")

    def _parse_item_card(self, card, keyword: str, base_url: str) -> Optional[dict]:
        """個別の商品カードをパースして辞書を返す"""

        # タイトル
        title_el = self._find_element_soup(card, config.SELECTORS["list"]["title"])
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        # タイトルキーワード除外（チケット・金券・商品券など）
        for kw in config.EXCLUDE_TITLE_KEYWORDS:
            if kw in title:
                logger.debug(f"キーワード除外 [{kw}]: {title[:60]}")
                return None

        # タイトル先頭メーカー名除外
        # 「送料無料 HITACHI 冷蔵庫...」のような先頭1〜2トークンにメーカー名が来るパターンを検出
        # ただし自動車・バイク・カー用品カテゴリ（AUTOMOTIVE_KEYWORDS にヒット）はスキップ
        _is_automotive = any(kw in title for kw in config.AUTOMOTIVE_KEYWORDS)
        if not _is_automotive:
            _title_tokens = title.split()
            _check_tokens = []
            for _tok in _title_tokens[:3]:
                if _tok in config.TITLE_STATUS_WORDS:
                    continue          # 状態ワードはスキップ
                _check_tokens.append(_tok)
                if len(_check_tokens) >= 2:
                    break             # 先頭から最大2トークン（状態ワード除く）を検査
            for _tok in _check_tokens:
                if _tok.lower() in config.EXCLUDE_MAKER_KEYWORDS:
                    logger.debug(f"メーカー名除外 [{_tok}]: {title[:60]}")
                    return None

        # 価格（数字を抽出）
        price_el = self._find_element_soup(card, config.SELECTORS["list"]["price"])
        price = self._extract_price(price_el.get_text(strip=True) if price_el else "0")

        # 価格フィルター（一覧取得段階で大まかに除外する）
        # 上限は MAX_PRICE×1.5 と緩めに設定し、詳細取得後の正確な価格で再判定する余地を残す。
        # セラー分析モード（skip_price_filter=True）では全商品を対象とするためスキップ。
        if not self.skip_price_filter:
            if price > 0 and (price < config.MIN_PRICE or price > config.MAX_PRICE * 1.5):
                return None

        # 商品状態を取得（<dt>商品状態</dt><dd>新品</dd> 構造から抽出）
        condition = ""
        for dt in card.find_all("dt"):
            if "商品状態" in dt.get_text():
                dd = dt.find_next_sibling("dd")
                if dd:
                    condition = dd.get_text(strip=True)
                break

        # STEP2/3モード（skip_price_filter=True）かつ SELLER_NEW_ONLY=true のとき
        # 商品状態が新品系ワードでない商品を除外する
        if self.skip_price_filter and config.SELLER_NEW_ONLY:
            if condition and not any(w in condition for w in config.SELLER_NEW_CONDITIONS):
                logger.debug(f"商品状態除外 [{condition}]: {title[:60]}")
                return None

        # セラーID + セラー検索URL（a.sellerLink の href を流用）
        seller_el = self._find_element_soup(card, config.SELECTORS["list"]["seller"])
        seller_id = seller_el.get_text(strip=True) if seller_el else ""
        seller_url = ""
        if seller_el:
            seller_href = seller_el.get("href", "")
            if seller_href:
                seller_url = seller_href if seller_href.startswith("http") else urljoin(base_url, seller_href)

        # 画像URL（AucFanは data-src-original で遅延読み込み）
        img_el = self._find_element_soup(card, config.SELECTORS["list"]["image"])
        thumbnail_url = ""
        if img_el:
            thumbnail_url = (
                img_el.get("data-src-original")
                or img_el.get("data-original")
                or img_el.get("data-src")
                or img_el.get("data-lazy-src")
                or img_el.get("src")
                or ""
            )
            if thumbnail_url and not thumbnail_url.startswith("http"):
                thumbnail_url = urljoin(base_url, thumbnail_url)
            # noimage プレースホルダーは除外
            if thumbnail_url and "noimage" in thumbnail_url:
                thumbnail_url = ""

        # 商品URL（hdLinkから取得）
        url_el = self._find_element_soup(card, config.SELECTORS["list"]["url"])
        if not url_el:
            url_el = card.find("a")
        item_url = ""
        if url_el:
            item_url = url_el.get("href", "")
            if item_url and not item_url.startswith("http"):
                item_url = urljoin(base_url, item_url)

        # サムネール画像ダウンロード（非同期にはしない）
        thumbnail_local = ""
        if thumbnail_url:
            local_path = self.img.download_image(thumbnail_url, prefix="thumb")
            if local_path:
                thumbnail_local = str(local_path)
                # pHash 計算
                phash_str = self.img.compute_phash(local_path)
            else:
                phash_str = ""
        else:
            phash_str = ""

        # 商品URLをキーにした安定ID（同一商品が異なるページで重複取得されたとき上書きになる）
        stable_id = (
            hashlib.md5(item_url.encode()).hexdigest()[:16]
            if item_url
            else None
        )

        # トレーディングカード関連フラグ（Gemini 判定で本体 vs アクセサリーを判別）
        needs_card_check = any(kw in title for kw in config.TRADING_CARD_KEYWORDS)
        if needs_card_check:
            logger.debug(f"トレカフラグ付与: {title[:60]}")

        return {
            "item_id": stable_id,       # URLベースの安定ID（None の場合は add_item が UUID を生成）
            "keyword": keyword,
            "title_short": title[:200],
            "price": price,
            "seller_id": seller_id,
            "seller_url": seller_url,   # a.sellerLink の href（セラー分析機能で使用）
            "url": item_url,
            "thumbnail_url": thumbnail_url,
            "thumbnail_local": thumbnail_local,
            "phash": phash_str,
            "needs_card_check": needs_card_check,  # トレカ本体 vs アクセサリー判定フラグ
        }

    # ─────────────────────────────────────────────
    # Step2: 詳細ページ取得
    # ─────────────────────────────────────────────

    def _scrape_detail_pages(self, target_statuses=None, min_group_size=None):
        """
        候補商品の詳細ページを取得する。

        Parameters
        ----------
        target_statuses : list[str] | None
            絞り込むステータスリスト。None の場合は STATUS_NG 以外の全候補。
        min_group_size : int | None
            グループ件数の下限フィルタ。None の場合は絞り込まない。
            セラー分析で min_group_size=1 により全件 candidate になる場合に
            group_size >= N の商品だけ詳細取得・Gemini判定するために使用。
            例: config.SELLER_DETAIL_MIN_GROUP (デフォルト 3)
        """
        all_targets = self.dm.get_unscraped_candidates()

        targets = all_targets
        if target_statuses is not None:
            targets = [item for item in targets if item.get("status") in target_statuses]
        if min_group_size is not None:
            targets = [item for item in targets if item.get("group_size", 1) >= min_group_size]

        if target_statuses is not None or min_group_size is not None:
            logger.info(
                f"詳細ページ取得対象: {len(targets)}件"
                f" (全候補: {len(all_targets)}件"
                + (f", ステータス絞り込み: {target_statuses}" if target_statuses else "")
                + (f", group_size >= {min_group_size}" if min_group_size else "")
                + ")"
            )
        else:
            logger.info(f"詳細ページ取得対象: {len(targets)}件")

        self._total_items = len(targets)
        self._processed_items = 0
        self.dm.update_progress(
            detail_pages_total=len(targets),
            detail_pages_done=0,
            processed_items=0,
        )

        done = 0
        errors = 0

        for item in targets:
            if self.stop_event.is_set():
                break

            item_id = item["item_id"]
            url = item.get("url", "")

            if not url:
                continue

            # 再開時: 既に詳細取得済みならスキップ
            if self.dm.is_detail_done(url):
                done += 1
                continue

            try:
                logger.info(f"詳細ページ [{done+1}/{len(targets)}]: {url}")
                detail = self._scrape_detail_page(url, item_id)

                if detail:
                    updates = {
                        "scraped_detail": True,
                        **detail,
                    }

                    # Gemini判定（タイトルが確定した後）
                    full_title = detail.get("title_full") or item.get("title_short", "")
                    if full_title and self.gemini.available:
                        gemini_result = self.gemini.classify_item_full(
                            full_title,
                            Path(detail.get("thumbnail_local", "")) if detail.get("thumbnail_local") else None
                        )
                        updates.update(gemini_result)

                        if gemini_result.get("excluded"):
                            updates["status"] = config.STATUS_NG
                            updates["exclude_reason"] = gemini_result.get("exclude_reason", "")
                            logger.info(f"  → 除外: {gemini_result.get('exclude_reason', '')}")
                        elif gemini_result.get("is_branded"):
                            updates["status"] = config.STATUS_NG
                            updates["exclude_reason"] = f"ブランド品: {gemini_result.get('brand_name', '')}"
                            logger.info(f"  → ブランド品除外: {gemini_result.get('brand_name', '')}")
                        elif gemini_result.get("needs_review"):
                            updates["status"] = config.STATUS_REVIEW
                            updates["needs_review"] = True
                            logger.info(f"  → 要確認フラグ: {gemini_result.get('review_reason', '')}")

                    self.dm.update_item(item_id, updates)
                    self.dm.mark_detail_done(url)

                done += 1
                errors = 0
                self._processed_items = done

                self.dm.update_progress(detail_pages_done=done, processed_items=done)

                # 定期保存
                if done % 20 == 0:
                    self.dm.save_all()

                self._random_wait()

            except Exception as e:
                logger.warning(f"詳細ページエラー ({url}): {e}")
                self.dm.add_error(f"詳細:{url}: {e}")
                errors += 1
                if errors >= 10:
                    logger.error("詳細ページ連続10回エラー。継続します。")
                    errors = 0
                self._random_wait()

        self.dm.save_all()
        logger.info(f"詳細ページ取得完了: {done}件")

    def _scrape_detail_page(self, url: str, item_id: str) -> Optional[dict]:
        """
        詳細ページをスクレイプして情報を返す。
        """
        if not self._navigate(url):
            return None

        try:
            WebDriverWait(self.driver, config.PAGE_LOAD_TIMEOUT).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            html = self.driver.page_source
        except Exception as e:
            logger.warning(f"詳細ページ読み込みエラー: {e}")
            return None

        soup = BeautifulSoup(html, "lxml")

        # 完全タイトル
        title_el = self._find_element_soup(soup, config.SELECTORS["detail"]["full_title"])
        title_full = title_el.get_text(strip=True) if title_el else ""

        # 送料
        shipping = self._extract_shipping(soup)

        # 複数画像
        img_urls = []
        for sel in config.SELECTORS["detail"]["images"]:
            imgs = soup.select(sel)
            if imgs:
                for img in imgs[:10]:  # 最大10枚
                    src = img.get("src") or img.get("data-src") or ""
                    if src and src.startswith("http") and src not in img_urls:
                        img_urls.append(src)
                if img_urls:
                    break

        # 画像ダウンロード
        images_local = []
        for i, img_url in enumerate(img_urls[:5]):  # 最大5枚DL
            local = self.img.download_image(img_url, prefix=f"detail_{item_id[:8]}_{i}")
            if local:
                images_local.append(str(local))

        # サイズ情報（テキストから抽出）
        size_info = self._extract_size_info(soup)

        # 価格を再取得（詳細ページで正確な値を取得）
        price_el = self._find_element_soup(soup, config.SELECTORS["list"]["price"])
        price = self._extract_price(price_el.get_text() if price_el else "")

        return {
            "title_full": title_full,
            "shipping": shipping,
            "total": (price or 0) + shipping,
            "images_local": images_local,
            "size_info": size_info,
        }

    # ─────────────────────────────────────────────
    # pHash グループ化
    # ─────────────────────────────────────────────

    def _run_phash_grouping(self):
        """pHashグループ化を実行してDataManagerを更新"""
        try:
            n = self.img.group_items(self.dm)
            candidates = self.dm.candidate_count
            logger.info(f"グループ化: {n}グループ / 候補: {candidates}件")
            self.dm.update_progress(candidates_found=candidates)
        except Exception as e:
            logger.error(f"pHashグループ化エラー: {e}")
            self.dm.add_error(f"pHashグループ化: {e}")

    def _run_vision_group_check(self):
        """
        pHashグループ化後に Gemini Vision API でグループ代表画像を判定。
        group_size >= config.VISION_MIN_GROUP_SIZE のグループを対象とする。
        詳細ページ取得済みアイテムは既に classify_item_full() 済みのためスキップ。
        """
        if not self.gemini.available:
            return

        try:
            groups = self.dm.get_groups()
        except Exception as e:
            logger.error(f"Vision判定: get_groups() 失敗: {e}")
            return

        targets = [
            (gid, members)
            for gid, members in groups.items()
            if len(members) >= config.VISION_MIN_GROUP_SIZE
        ]
        logger.info(
            f"=== Vision判定: {len(targets)}グループ対象 "
            f"(group_size>={config.VISION_MIN_GROUP_SIZE}) ==="
        )

        for gid, members in targets:
            if self.stop_event.is_set():
                break

            # 既に全員 NG or OK なら Vision 判定不要
            non_ng = [m for m in members if m.get("status") != config.STATUS_NG]
            if not non_ng:
                continue

            # 詳細取得済み（Gemini テキスト判定済み）アイテムがある場合はスキップ
            # （detail_done フラグがあるものが1件以上いればグループ判定は済んでいる）
            if any(m.get("detail_done") for m in members):
                continue

            # 代表アイテム：thumbnail_local がある最初のもの
            rep = next(
                (m for m in members if m.get("thumbnail_local")),
                None,
            )
            if rep is None:
                continue

            title = rep.get("title_short", "")
            thumb = Path(rep["thumbnail_local"])

            logger.info(
                f"  Vision判定: グループ {gid} ({len(members)}件) "
                f"代表='{title[:30]}'"
            )

            result = self.gemini.classify_item_full(title, thumb)

            gemini_source = result.get("gemini_source", "vision")
            gemini_reason = result.get("gemini_reason", "")

            if result.get("excluded") or result.get("is_branded"):
                reason = result.get("exclude_reason", "Vision除外判定")
                logger.info(f"    → NG: {reason}")
                for m in members:
                    self.dm.update_item(
                        m["item_id"],
                        {
                            "status": config.STATUS_NG,
                            "exclude_reason": reason,
                            "gemini_source": gemini_source,
                            "gemini_reason": gemini_reason or reason,
                        },
                    )
            elif result.get("needs_review"):
                reason = result.get("review_reason", "Vision要確認判定")
                logger.info(f"    → 要確認: {reason}")
                for m in members:
                    # 既に NG のものは上書きしない
                    if m.get("status") != config.STATUS_NG:
                        self.dm.update_item(
                            m["item_id"],
                            {
                                "status": config.STATUS_REVIEW,
                                "needs_review": True,
                                "gemini_source": gemini_source,
                                "gemini_reason": gemini_reason or reason,
                            },
                        )

    # ─────────────────────────────────────────────
    # ナビゲーション・待機
    # ─────────────────────────────────────────────

    def _navigate(self, url: str) -> bool:
        """URLに移動。失敗したら False を返す（例外はキャッチ）"""
        try:
            self.driver.get(url)
            return True
        except Exception as e:
            logger.warning(f"ページ移動失敗 {url}: {e}")
            self.dm.add_error(f"移動失敗: {url}: {e}")
            return False

    def _random_wait(self):
        """ランダム待機（3〜5秒）"""
        wait = random.uniform(config.MIN_DELAY, config.MAX_DELAY)
        logger.debug(f"待機: {wait:.1f}秒")
        time.sleep(wait)

    # ─────────────────────────────────────────────
    # ページネーション
    # ─────────────────────────────────────────────

    def _get_next_page_url(self, current_url: str, current_page: int) -> Optional[str]:
        """
        次ページのURLを取得する。
        1. 「次へ」ボタンの CSS セレクターを探す
        2. AucFan 固有: ?o=p{next} を含むリンクを探す
        3. どちらも見つからなければフォールバック（?o=pN を付与）
           ※ フォールバックは stable item_id + new_count==0 検出で安全に停止できる

        【URL マージの注意】
        AucFan のページャーリンクが ?o=p2 形式（クエリ相対URL）の場合、
        urljoin では ?seller=XYZ が失われるため _merge_next_url を使う。
        """
        try:
            html = self.driver.page_source
            soup = BeautifulSoup(html, "lxml")

            # 1. CSS セレクターで「次へ」ボタンを探す
            for sel in config.SELECTORS["list"]["next_page"]:
                el = soup.select_one(sel)
                if el and el.get("href"):
                    href = el["href"]
                    merged = self._merge_next_url(current_url, href)
                    logger.debug(f"次ページリンク発見 (CSS): {merged}")
                    return merged

            # 2. AucFan 固有: ?o=p{N+1} を含む <a> を探す
            next_o_param = f"o=p{current_page + 1}"
            for a in soup.find_all("a", href=True):
                if next_o_param in a["href"]:
                    href = a["href"]
                    merged = self._merge_next_url(current_url, href)
                    logger.debug(f"次ページリンク発見 (o=pN): {merged}")
                    return merged

        except Exception as e:
            logger.debug(f"次ページURL取得エラー: {e}")

        # 3. フォールバック: AucFan形式 ?o=pN で次ページ生成
        #    （stable item_id + new_count==0 検出で同一ページ無限ループは防止済み）
        fallback = self._build_page_url_aucfan(current_url, current_page + 1)
        logger.debug(f"次ページリンクなし → フォールバック: {fallback}")
        return fallback

    def _merge_next_url(self, current_url: str, href: str) -> str:
        """
        AucFan のページャーリンク href を現在の URL とマージして次ページ URL を返す。

        【問題】href が ?o=p2 形式（クエリ文字列のみ）のとき urljoin を使うと
                ?seller=XYZ など現在URLのクエリパラメータが失われる。
        【解決】href が ? 始まりのときは現在URLのクエリと href のクエリをマージする。
        """
        if not href:
            return current_url
        if href.startswith("http"):
            return href
        if href.startswith("?"):
            # クエリ相対URL: 現在URLのパラメータに href のパラメータを上書きマージ
            parsed = urlparse(current_url)
            base_params = parse_qs(parsed.query)
            new_params = parse_qs(href.lstrip("?"))
            merged = {**base_params, **new_params}  # href 側が優先
            new_query = urlencode({k: v[0] for k, v in merged.items()})
            return urlunparse(parsed._replace(query=new_query))
        # パス相対URL または /-始まり: 通常の urljoin
        return urljoin(current_url, href)

    def _build_page_url(self, base_url: str, page: int) -> str:
        """URLにページ番号を付与"""
        try:
            parsed = urlparse(base_url)
            params = parse_qs(parsed.query)

            # AucFan のページパラメータを試す
            for param_name in ("page", "p", "pg", "start"):
                if param_name in params or page > 1:
                    params[param_name] = [str(page)]
                    new_query = urlencode({k: v[0] for k, v in params.items()})
                    return urlunparse(parsed._replace(query=new_query))
        except Exception:
            pass

        # デフォルト: ?page=N を追加
        sep = "&" if "?" in base_url else "?"
        # 既存の page パラメータを除去
        url = re.sub(r"[&?]page=\d+", "", base_url)
        return f"{url}{sep}page={page}"

    # ─────────────────────────────────────────────
    # HTML パース ユーティリティ
    # ─────────────────────────────────────────────

    def _find_elements_soup(self, soup, selectors: List[str]):
        """複数セレクターを順に試して最初にヒットしたリストを返す"""
        for sel in selectors:
            try:
                els = soup.select(sel)
                if els:
                    return els
            except Exception:
                continue
        return []

    def _find_element_soup(self, soup, selectors: List[str]):
        """複数セレクターを順に試して最初にヒットした要素を返す"""
        for sel in selectors:
            try:
                el = soup.select_one(sel)
                if el:
                    return el
            except Exception:
                continue
        return None

    def _extract_price(self, text: str) -> int:
        """テキストから価格（数値）を抽出"""
        if not text:
            return 0
        # カンマ・円記号・スペースを除去して数字を抽出
        nums = re.findall(r"[\d,]+", text.replace(",", ""))
        for num_str in nums:
            try:
                val = int(num_str.replace(",", ""))
                if 100 <= val <= 100000:  # 妥当な価格範囲
                    return val
            except ValueError:
                continue
        return 0

    def _extract_shipping(self, soup) -> int:
        """
        詳細ページから送料を抽出。
        「送料無料」→ 0、数字 → その値、不明 → 0
        """
        for sel in config.SELECTORS["detail"]["shipping"]:
            try:
                el = soup.select_one(sel)
                if not el:
                    continue
                text = el.get_text(strip=True)
                if "無料" in text or "込" in text or "0円" in text:
                    return 0
                nums = re.findall(r"[\d,]+", text)
                for n in nums:
                    v = int(n.replace(",", ""))
                    if 0 < v < 10000:
                        return v
            except Exception:
                continue

        # 全テキストから送料を検索
        full_text = soup.get_text()
        patterns = [
            r"送料[：:]\s*([\d,]+)円",
            r"配送料[：:]\s*([\d,]+)円",
            r"([\d,]+)円.*送料",
        ]
        for pat in patterns:
            m = re.search(pat, full_text)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except Exception:
                    pass

        if "送料無料" in full_text or "送料込" in full_text:
            return 0

        return 0  # 不明な場合は0として処理

    def _extract_size_info(self, soup) -> str:
        """詳細ページからサイズ情報を抽出"""
        for sel in config.SELECTORS["detail"]["size"]:
            try:
                el = soup.select_one(sel)
                if el:
                    return el.get_text(strip=True)
            except Exception:
                continue

        # テキストからサイズっぽい情報を検索
        full_text = soup.get_text()
        patterns = [
            r"(\d+)\s*[×xX]\s*(\d+)\s*[×xX]\s*(\d+)\s*cm",
            r"サイズ[：:]\s*(.{5,50})",
            r"梱包[：:]\s*(.{5,50})",
        ]
        for pat in patterns:
            m = re.search(pat, full_text)
            if m:
                return m.group(0)

        return ""

    def _extract_keyword_from_url(self, url: str) -> str:
        """
        URLからキーワードを抽出。
        AucFan形式: /search1/q-~a5aba1bca5dca5f3/... （パスにエンコード）
        通常形式:   ?q=keyword
        """
        try:
            from urllib.parse import unquote
            parsed = urlparse(url)

            # AucFan 形式: パスの /q-XXX/ 部分からキーワードを取得
            import re as _re
            m = _re.search(r'/q-([^/]+)/', parsed.path)
            if m:
                encoded = m.group(1)
                # ~XX形式のURL encoding（EUC-JPベース）をデコード試行
                try:
                    hex_str = encoded.replace("~", "%").upper()
                    decoded = unquote(hex_str, encoding="euc-jp", errors="ignore")
                    if decoded and decoded != encoded:
                        return decoded
                except Exception:
                    pass
                return encoded  # デコードできなければそのまま返す

            # 通常のクエリパラメータ形式
            params = parse_qs(parsed.query)
            for key in ("q", "query", "keyword", "kw", "s"):
                if key in params:
                    return unquote(params[key][0])
        except Exception:
            pass
        return ""

    def _build_page_url_aucfan(self, base_url: str, page: int) -> str:
        """AucFan 専用ページネーション: ?o=pN パラメータを付与

        AucFan のページネーション形式:
          1ページ目: パラメータなし（o= を除去）
          2ページ目以降: ?o=p2, ?o=p3, ...
        ※ 旧実装は ?p=N を使っていたが、AucFan は ?o=pN が正しい形式。
        """
        try:
            parsed = urlparse(base_url)
            params = parse_qs(parsed.query)
            # 古い p= パラメータは必ず除去
            params.pop("p", None)
            if page <= 1:
                # 1ページ目は o= パラメータを除去
                params.pop("o", None)
            else:
                # 2ページ目以降は o=p2, o=p3, ...
                params["o"] = [f"p{page}"]
            new_query = urlencode({k: v[0] for k, v in params.items()})
            return urlunparse(parsed._replace(query=new_query))
        except Exception:
            return base_url
