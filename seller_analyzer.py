"""
seller_analyzer.py — セラーリサーチ スクレイピング

【役割】
  STEP 2 / STEP 3 で使用するセラー分析クラス。
  AucFanScraper を継承し、run() と _run_phash_grouping() をオーバーライドして
  複数セラーの商品を 1 セッションにまとめて収集・グループ化する。

【フロー（デフォルト: scrape_detail=False）】
  1. Chrome に 1 回接続（start.sh で起動したデバッグポート付き Chrome）
  2. セラーリストを順番に処理:
       各セラー URL に「現在タブで直接ナビゲート」→ _scrape_list_pages() → 次のセラーへ
       ★ window.open / driver.close() は使わない（セッション切れの原因になるため）
  3. 全セラー完了後、まとめて pHash グループ化（min_group_size=1 で全件 candidate 化）
     → サムネイル・pHash は一覧取得時に完了しているため詳細取得は不要
     → Gemini Vision 判定も実行（グループ代表画像+タイトルで判定）
  4. 結果を 1 つの DataManager / セッションフォルダに集約

【フロー（scrape_detail=True の場合）】
  上記フローに加え:
  3b. group_size >= SELLER_DETAIL_MIN_GROUP の候補商品だけ詳細ページ取得
      （全商品が candidate になるため group_size フィルターで対象を絞る）
  3c. 詳細取得後に再グループ化 + Gemini Vision 判定

【skip_price_filter=True】
  親クラスの価格フィルター（MIN_PRICE / MAX_PRICE）をオフにして全商品を取得する。
  セラーが繰り返し出品している商品を漏れなく検出するため。

【主な変更履歴】
  v2: window.open + driver.close() 廃止（invalid session id の原因だった）
      MIN_GROUP_SIZE を 1 に固定して全商品を候補として表示
  v3: scrape_detail=False をデフォルトに変更（詳細取得は .env で SELLER_SCRAPE_DETAIL=true 時のみ）
"""
import logging
import os
import threading
from typing import Callable, List, Optional

import config
from scraper import AucFanScraper

logger = logging.getLogger(__name__)

# デフォルト: 詳細ページ取得をスキップ（True にすると旧動作）
# .env に SELLER_SCRAPE_DETAIL=true と書くことで有効化できる
_SELLER_SCRAPE_DETAIL_DEFAULT = os.getenv("SELLER_SCRAPE_DETAIL", "false").lower() == "true"


class SellerAnalyzer(AucFanScraper):
    """
    複数セラーを 1 セッションにまとめてスクレイピングする。

    Parameters
    ----------
    sellers : list of dict
        [{"seller_id": str, "seller_url": str}, ...]
    data_manager : DataManager
    image_processor : ImageProcessor
    gemini_client : GeminiClient
    stop_event : threading.Event
    on_seller_progress : callable(index: int, status: str) | None
        各セラーのステータスが変化したときに呼ばれるコールバック。
        status は "running" / "done" / "error" のいずれか。
    """

    def __init__(
        self,
        sellers: List[dict],
        data_manager,
        image_processor,
        gemini_client,
        stop_event: threading.Event,
        on_seller_progress: Optional[Callable[[int, str], None]] = None,
        scrape_detail: Optional[bool] = None,
    ):
        super().__init__(data_manager, image_processor, gemini_client, stop_event)
        self.sellers = sellers
        self.on_seller_progress = on_seller_progress
        # セラー分析では価格フィルタをオフにして全商品を取得する
        self.skip_price_filter = True
        # 詳細ページ取得フラグ（デフォルト: False でスキップ）
        # 引数で明示指定されなければ .env の SELLER_SCRAPE_DETAIL を参照
        self.scrape_detail = scrape_detail if scrape_detail is not None else _SELLER_SCRAPE_DETAIL_DEFAULT

    # ─────────────────────────────────────────────
    # メインフロー（AucFanScraper.run() をオーバーライド）
    # ─────────────────────────────────────────────

    def run(self, resume: bool = False, start_url: Optional[str] = None):
        """
        全セラーを順番にスクレイプして 1 セッションにまとめる。
        引数 resume / start_url は互換性のために残すが使用しない。
        """
        logger.info(f"=== セラー分析スクレイピング開始: {len(self.sellers)} 件 ===")

        if not self.connect_to_chrome():
            self.dm.update_progress(status="error")
            return

        try:
            self.dm.update_progress(status="scraping_list", keyword="seller_analysis")

            # ── Step 1: 各セラーの一覧ページを順番に取得 ──
            for i, seller in enumerate(self.sellers):
                if self.stop_event.is_set():
                    logger.info("停止リクエスト受信 → 一覧取得を中断")
                    break

                seller_id = seller["seller_id"]
                seller_url = seller.get("seller_url", "").strip()
                if not seller_url:
                    seller_url = (
                        f"https://aucfan.com/search1/?aucnm={seller_id}"
                    )
                    logger.info(
                        f"seller_url 未設定 → フォールバック URL: {seller_url}"
                    )

                total = len(self.sellers)
                seller_short = seller_id[:20] + ("..." if len(seller_id) > 20 else "")
                logger.info(
                    f"[セラー {i + 1}/{total}] {seller_short} スクレイピング開始"
                    f"  URL={seller_url}"
                )
                self._notify(i, "running")

                try:
                    # ★ 現在タブを直接セラー URL へナビゲート
                    #   （window.open + driver.close() はセッションが切れる原因になるため使わない）
                    self._navigate(seller_url)

                    # 一覧ページを全ページ取得（親クラスのメソッドをそのまま使用）
                    self._scrape_list_pages(seller_url)

                    self._notify(i, "done")
                    logger.info(
                        f"[セラー {i + 1}/{total}] {seller_short} 完了"
                        f"  累計: {self.dm.total_items} 件"
                    )

                except Exception as e:
                    logger.error(
                        f"[セラー {i + 1}/{total}] {seller_short} エラー: {e}"
                    )
                    self.dm.add_error(f"セラー {seller_id}: {e}")
                    self._notify(i, "error")
                    continue

            # ── Step 2: pHash グループ化（min_group_size=1） ──
            if not self.stop_event.is_set():
                logger.info("=== pHash グループ化 ===")
                self.dm.update_progress(status="grouping")
                self._run_phash_grouping()

            # ── Step 3: 候補のみ詳細ページ取得 + Gemini判定 ──
            #   グループ化で candidate / next_candidate になった商品だけが対象。
            #   45,000件全件でなく「数百件の候補」だけ詳細取得するため現実的な時間で完了。
            #   scrape_detail=False の場合はこのステップをスキップ（サムネイル・pHashのみで完了）。
            if self.scrape_detail and not self.stop_event.is_set():
                # group_size >= SELLER_DETAIL_MIN_GROUP の商品のみ詳細取得・Gemini判定。
                # min_group_size=1 により全件 candidate になる問題を group_size フィルタで解決。
                # ステータスフィルタは念のため残すが、実質的な絞り込みは group_size が担う。
                _target_statuses = [
                    config.STATUS_CANDIDATE,
                    config.STATUS_NEXT_CANDIDATE,
                ]
                _min_group = config.SELLER_DETAIL_MIN_GROUP
                detail_count = sum(
                    1 for item in self.dm.get_all_items()
                    if item.get("status") in _target_statuses
                    and item.get("group_size", 1) >= _min_group
                )
                logger.info(
                    f"=== 詳細ページ取得: {detail_count}件"
                    f" (group_size >= {_min_group} / SELLER_DETAIL_MIN_GROUP) ==="
                )
                self.dm.update_progress(status="scraping_detail")
                self._scrape_detail_pages(
                    target_statuses=_target_statuses,
                    min_group_size=_min_group,
                )

                # 詳細取得後に最終グループ化（画像更新があるため）
                if not self.stop_event.is_set():
                    logger.info("=== 最終グループ化 ===")
                    self._run_phash_grouping()

                # Vision判定（詳細取得 + 最終グループ化の後）
                if not self.stop_event.is_set():
                    self.dm.update_progress(status="vision_check")
                    self._run_vision_group_check()
            else:
                logger.info(
                    "詳細ページ取得をスキップ（scrape_detail=False）"
                    " → 一覧取得済みのサムネイル・pHashで完了"
                )
                # scrape_detail=False でも Vision判定は実行する
                if not self.stop_event.is_set():
                    self.dm.update_progress(status="vision_check")
                    self._run_vision_group_check()

            final_status = "stopped" if self.stop_event.is_set() else "done"
            self.dm.update_progress(status=final_status)
            logger.info("=" * 50)
            logger.info(
                f"=== セラー分析スクレイピング完了 === 全{self.dm.total_items}件処理"
                f" ({final_status})"
            )
            logger.info("=" * 50)

        except Exception as e:
            logger.error(
                f"セラー分析中に予期しないエラー: {e}", exc_info=True
            )
            self.dm.update_progress(status="error")
            self.dm.add_error(str(e))

        finally:
            self.dm.save_all()
            try:
                if self.driver:
                    self.driver.quit()
            except Exception:
                pass

    # ─────────────────────────────────────────────
    # pHash グループ化（min_group_size=1 でオーバーライド）
    # ─────────────────────────────────────────────

    def _run_phash_grouping(self):
        """
        pHash グループ化を実行。
        セラー分析では全商品を表示したいため min_group_size=1 に固定する。
        （キーワードリサーチの MIN_GROUP_SIZE=5 は適用しない）
        """
        try:
            n = self.img.group_items_with_min_size(self.dm, min_group_size=1)
            candidates = self.dm.candidate_count
            logger.info(f"グループ化: {n}グループ / 候補: {candidates}件 (min_group_size=1)")
            self.dm.update_progress(candidates_found=candidates)
        except Exception as e:
            logger.error(f"pHashグループ化エラー: {e}")
            self.dm.add_error(f"pHashグループ化: {e}")

    # ─────────────────────────────────────────────
    # ユーティリティ
    # ─────────────────────────────────────────────

    def _notify(self, index: int, status: str):
        """セラーごとの進捗をコールバックで通知"""
        if self.on_seller_progress:
            try:
                self.on_seller_progress(index, status)
            except Exception:
                pass
