"""
scraper.py - AucFan Selenium スクレイパー
- 既存 Chrome に接続（リモートデバッグ）
- 一覧ページ全件取得（Step1）
- 候補のみ詳細ページ取得（Step2）
- 3〜5秒ランダム待機
- エラーがあっても継続
- 途中停止・再開対応
"""
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

            # AucFanタブに切り替え
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                current = self.driver.current_url
                if "aucfan.com" in current:
                    logger.info(f"AucFanタブに切り替えました: {current}")
                    break
            else:
                logger.warning("AucFanタブが見つかりません。現在のタブで続行します: " + self.driver.current_url)

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

    def run(self, resume: bool = False):
        """
        スクレイピングのメインフロー。
        Step1: 一覧ページ → Step2: 詳細ページ（候補のみ）
        """
        logger.info("=== AucFan スクレイピング開始 ===")

        if not self.connect_to_chrome():
            self.dm.update_progress(status="error")
            return

        try:
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

            final_status = "stopped" if self.stop_event.is_set() else "done"
            self.dm.update_progress(status=final_status)
            logger.info(f"=== スクレイピング完了 ({final_status}) ===")

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
            logger.info(f"[一覧] ページ {page} / {config.MAX_PAGES}: {current_url}")

            try:
                # ページ解析
                items = self._parse_list_page()

                if not items:
                    logger.warning(f"ページ {page}: アイテムが見つかりません")
                    consecutive_errors += 1
                    if consecutive_errors >= 5:
                        logger.error("連続5ページ空白のため一覧取得を終了します")
                        break
                else:
                    consecutive_errors = 0
                    logger.info(f"ページ {page}: {len(items)}件取得")

                    for item in items:
                        self.dm.add_item(item)

                    self.dm.update_progress(
                        pages_done=page,
                        total_items=self.dm.total_items,
                    )

                # 定期保存（10ページごと）
                if page % 10 == 0:
                    self.dm.save_all()

                # 次のページへ
                next_url = self._get_next_page_url(current_url, page)
                if not next_url:
                    logger.info("次のページが見つかりません。一覧取得完了。")
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
                logger.warning(f"ページ {page} でエラー: {e}")
                self.dm.add_error(f"ページ{page}: {e}")
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    logger.error("連続5回エラーのため一覧取得を終了します")
                    break
                self._random_wait()
                continue

        logger.info(f"一覧取得完了: {self.dm.total_items}件")
        self.dm.save_all()

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
            logger.warning(f"ページソース取得エラー: {e}")
            return []

        soup = BeautifulSoup(html, "lxml")
        items = []

        # 商品カードを探す（複数セレクターを試す）
        cards = self._find_elements_soup(soup, config.SELECTORS["list"]["item_cards"])

        if not cards:
            logger.debug("商品カードが見つかりません（セレクターを確認してください）")
            return []

        current_url = self.driver.current_url
        keyword = self._extract_keyword_from_url(current_url)

        for card in cards:
            try:
                item = self._parse_item_card(card, keyword, current_url)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"カードパースエラー: {e}")
                continue

        return items

    def _parse_item_card(self, card, keyword: str, base_url: str) -> Optional[dict]:
        """個別の商品カードをパースして辞書を返す"""

        # タイトル
        title_el = self._find_element_soup(card, config.SELECTORS["list"]["title"])
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        # 価格（数字を抽出）
        price_el = self._find_element_soup(card, config.SELECTORS["list"]["price"])
        price = self._extract_price(price_el.get_text(strip=True) if price_el else "0")

        # 価格フィルター（一覧段階で大まかに絞る）
        if price > 0 and (price < config.MIN_PRICE or price > config.MAX_PRICE * 1.5):
            return None

        # セラーID
        seller_el = self._find_element_soup(card, config.SELECTORS["list"]["seller"])
        seller_id = seller_el.get_text(strip=True) if seller_el else ""

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

        return {
            "keyword": keyword,
            "title_short": title[:200],
            "price": price,
            "seller_id": seller_id,
            "url": item_url,
            "thumbnail_url": thumbnail_url,
            "thumbnail_local": thumbnail_local,
            "phash": phash_str,
        }

    # ─────────────────────────────────────────────
    # Step2: 詳細ページ取得
    # ─────────────────────────────────────────────

    def _scrape_detail_pages(self):
        """
        候補商品の詳細ページを取得する（グループ5件以上 or 全候補）。
        """
        # 詳細取得対象: 候補または確認待ちで未取得のもの
        targets = self.dm.get_unscraped_candidates()
        logger.info(f"詳細ページ取得対象: {len(targets)}件")

        self.dm.update_progress(
            detail_pages_total=len(targets),
            detail_pages_done=0,
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

                self.dm.update_progress(detail_pages_done=done)

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
        1. 「次へ」ボタンを探す
        2. なければURL パラメータを page+1 に変更
        """
        try:
            # HTMLから次ページリンクを探す
            html = self.driver.page_source
            soup = BeautifulSoup(html, "lxml")

            for sel in config.SELECTORS["list"]["next_page"]:
                el = soup.select_one(sel)
                if el and el.get("href"):
                    href = el["href"]
                    if not href.startswith("http"):
                        href = urljoin(current_url, href)
                    return href
        except Exception:
            pass

        # フォールバック: AucFan形式 ?p=N で次ページ生成
        return self._build_page_url_aucfan(current_url, current_page + 1)

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
        """AucFan 専用ページネーション: ?p=N パラメータを付与"""
        try:
            parsed = urlparse(base_url)
            params = parse_qs(parsed.query)
            params["p"] = [str(page)]
            # p=1 の場合は除去（1ページ目はパラメータなし）
            if page == 1 and "p" in params:
                del params["p"]
            new_query = urlencode({k: v[0] for k, v in params.items()})
            return urlunparse(parsed._replace(query=new_query))
        except Exception:
            return base_url
