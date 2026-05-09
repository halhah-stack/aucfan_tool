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
        login_check_event: Optional[threading.Event] = None,
    ):
        super().__init__(data_manager, image_processor, gemini_client, stop_event,
                         login_check_event=login_check_event)
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

                    # このセラーのスクレイピング開始前のアイテムIDを記録
                    ids_before = {item["item_id"] for item in self.dm.get_all_items()}

                    # 中古カウンターをリセット（セラーごとに独立してカウント）
                    self._seller_used_count = 0
                    self._seller_skipped_by_used = False

                    self._navigate(seller_url)

                    # 一覧ページを全ページ取得（親クラスのメソッドをそのまま使用）
                    self._scrape_list_pages(seller_url)

                    # ── 中古セラー判定 ──
                    # _scrape_list_pages 内で中古累計が閾値超えなら打ち切り済み。
                    # 取得済みデータを削除して次のセラーへ進む。
                    if self._seller_skipped_by_used:
                        ids_after = {item["item_id"] for item in self.dm.get_all_items()}
                        ids_to_remove = ids_after - ids_before
                        if ids_to_remove:
                            self.dm.remove_items(ids_to_remove)
                        used_cnt = self._seller_used_count
                        thresh   = config.SELLER_USED_SKIP_THRESHOLD
                        self._notify(i, "used_skip", {"used_count": used_cnt})
                        msg = (
                            f"[セラー {i + 1}/{total}] {seller_short}"
                            f" → 中古 {used_cnt}件（上限 {thresh}件）のためスキップ"
                            f" | 取得データ {len(ids_to_remove)}件を除外"
                            f" | 累計 {self.dm.total_items}件"
                        )
                        logger.info(msg)
                        print(f"\n{'─'*60}")
                        print(f"🚫 中古セラースキップ: {seller_id}")
                        print(f"   中古件数: {used_cnt}件（閾値: {thresh}件超でスキップ）")
                        print(f"   取得データ {len(ids_to_remove)}件を除外しました")
                        print(f"{'─'*60}\n")
                        continue

                    self._notify(i, "done")
                    logger.info(
                        f"[セラー {i + 1}/{total}] {seller_short} 完了"
                        f"  累計: {self.dm.total_items} 件"
                    )

                    # ── 中間インクリメンタルpHashグループ化 ──
                    # 新規取得アイテムのみを既存グループと比較して割り当てる。
                    # 全件を毎回比較するより大幅に高速で、MAX_PHASH_ITEMS の上限にも当たりにくい。
                    if not self.stop_event.is_set():
                        ids_after = {item["item_id"] for item in self.dm.get_all_items()}
                        new_ids = ids_after - ids_before
                        if new_ids:
                            self._incremental_phash_group(new_ids)

                except Exception as e:
                    logger.error(
                        f"[セラー {i + 1}/{total}] {seller_short} エラー: {e}"
                    )
                    self.dm.add_error(f"セラー {seller_id}: {e}")
                    self._notify(i, "error")
                    continue

            # ── Step 2: グループ代表マージ（件数上限なし・高速） ──
            # インクリメンタルグループ化で各セラー内・セラー間のグループ化は完了済み。
            # このステップでは「グループ代表ハッシュ同士」だけを比較してグループをマージする。
            # 全アイテムを比較する _run_phash_grouping() と異なり、代表件数（グループ数）
            # だけを比較するため件数上限に引っかからない。
            #   例: 42,500件・5,000グループ → 代表5,000件の比較で完了（秒単位）
            if not self.stop_event.is_set():
                self.dm.update_progress(status="grouping")
                self._merge_groups_by_phash()

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

                # 詳細取得後に最終グループ化（代表マージ方式・件数上限なし）
                if not self.stop_event.is_set():
                    self._merge_groups_by_phash()

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
    # インクリメンタル pHash グループ化
    # ─────────────────────────────────────────────

    def _incremental_phash_group(self, new_item_ids: set):
        """
        今回のセラーで新規取得したアイテムのみを対象に pHash グループ化を行う。

        既存グループの「代表ハッシュ」と新規アイテムを比較し、
          - 一致 → 既存グループに追加
          - 不一致 → 新規グループを作成
        全アイテムを毎回全件比較する _run_phash_grouping() より大幅に高速で、
        MAX_PHASH_ITEMS 上限にも当たりにくい。

        Args:
            new_item_ids: 今回スクレイピングで追加されたアイテム ID のセット
        """
        if not new_item_ids:
            return

        all_items = self.dm.get_all_items()

        # ── 既存グループの代表ハッシュとメンバーを収集（既存アイテムのみ） ──
        # group_id == item_id のアイテムが各グループの「代表」
        existing_members: dict = {}   # group_id -> [item_id, ...]
        group_rep_hash: dict  = {}    # group_id -> phash

        for item in all_items:
            if item["item_id"] in new_item_ids:
                continue  # 新規アイテムはスキップ
            gid = item.get("group_id") or item["item_id"]
            existing_members.setdefault(gid, []).append(item["item_id"])
            # グループ代表（group_id == item_id）からハッシュを取得
            if gid == item["item_id"] and item.get("phash"):
                group_rep_hash[gid] = item["phash"]

        # 代表ハッシュリスト: [(phash, group_id)]
        rep_list = [(ph, gid) for gid, ph in group_rep_hash.items()]

        # ── 新規アイテムを既存グループ or 新規グループへ割り当て ──
        new_items = [i for i in all_items if i["item_id"] in new_item_ids]

        additions: dict = {}     # group_id -> [new_item_id, ...]（既存グループへの追加分）
        fresh_groups: list = []  # [(rep_phash, [item_id, ...])]（新規グループ）

        for item in new_items:
            ph = item.get("phash")
            if not ph:
                # pHash なし → 個別グループとして即登録
                self.dm.assign_group([item["item_id"]], item["item_id"])
                continue

            matched = False

            # 既存グループ代表と比較
            for rep_hash, gid in rep_list:
                if self.img.is_same_image(ph, rep_hash):
                    additions.setdefault(gid, []).append(item["item_id"])
                    matched = True
                    break

            if not matched:
                # 今回の新規グループと比較（セラー内での重複検出）
                for rep_hash, members in fresh_groups:
                    if self.img.is_same_image(ph, rep_hash):
                        members.append(item["item_id"])
                        matched = True
                        break

            if not matched:
                # 完全な新規グループを作成
                fresh_groups.append((ph, [item["item_id"]]))

        # ── バッチ割り当て ──
        # 既存グループへの追加（現メンバー + 新メンバーでまとめて assign_group）
        for gid, new_members in additions.items():
            current = existing_members.get(gid, [])
            self.dm.assign_group(current + new_members, gid)

        # 新規グループを登録（最初のアイテムが group_id = 代表）
        for _, members in fresh_groups:
            self.dm.assign_group(members, members[0])

        # 全アイテムを candidate に昇格（min_group_size=1 → 全件対象）
        self.dm.promote_candidates(min_group_size=1)

        n_added = sum(len(v) for v in additions.values())
        n_fresh = sum(len(m) for _, m in fresh_groups)
        logger.info(
            f"インクリメンタルpHash: {len(new_item_ids)}件入力 / "
            f"既存グループ追加: {n_added}件 / "
            f"新規グループ: {len(fresh_groups)}件 ({n_fresh}件)"
        )

    # ─────────────────────────────────────────────
    # グループ代表マージ（件数上限なし）
    # ─────────────────────────────────────────────

    def _merge_groups_by_phash(self):
        """
        インクリメンタルグループ化完了後に「グループ代表ハッシュ同士」を比較し、
        類似グループをまとめて最終的なグループを確定する。

        全アイテムを比較する _run_phash_grouping() と異なり、
        代表アイテム数（グループ数）だけを比較するため高速で件数上限がない。
          例: 42,500件・5,000グループ → 代表5,000件の比較で完了

        【最適化】
        - pHash文字列を imagehash オブジェクトに事前一括変換し、
          ループ内で hex_to_hash() を繰り返し呼ばない
        - 500グループごとに進捗ログを出力して「止まっているように見える」問題を解消
        - stop_event を 100グループごとにチェックし、停止リクエストに応答する
        """
        all_items = self.dm.get_all_items()

        # グループ代表（group_id == item_id）のハッシュとメンバーを収集
        # {group_id: {"phash": str, "members": [item_id, ...]}}
        groups: dict = {}
        for item in all_items:
            gid = item.get("group_id") or item["item_id"]
            if gid not in groups:
                groups[gid] = {"phash": None, "members": []}
            groups[gid]["members"].append(item["item_id"])
            if gid == item["item_id"] and item.get("phash"):
                groups[gid]["phash"] = item["phash"]

        # pHash がある代表のみ対象
        reps_str = [(gid, info["phash"], info["members"])
                    for gid, info in groups.items() if info["phash"]]
        n = len(reps_str)

        logger.info(f"=== グループ代表マージ: {n:,}グループ (全{self.dm.total_items:,}件) ===")
        print(f"\n>>> グループ代表マージ開始: {n:,}グループ <<<")

        # ── 最適化: pHash文字列をオブジェクトに一括変換 ──
        # ループ内で毎回 hex_to_hash() を呼ぶと O(G²) 回の文字列パースが発生する。
        # 事前に変換しておくことで比較コストを大幅に削減する。
        reps = []
        for gid, phash_str, members in reps_str:
            phash_obj = self.img.str_to_phash(phash_str)
            if phash_obj is not None:
                reps.append((gid, phash_obj, members))

        # 代表ハッシュ比較（事前変換済みオブジェクト使用）
        # merged: [(代表gid, 代表phash_obj, [member gid, ...])]
        merged: list = []
        for i, (gid, phash_obj, members) in enumerate(reps):
            # stop_event チェック（100グループごと）
            if i % 100 == 0 and self.stop_event.is_set():
                logger.info("グループ代表マージ: 停止リクエストを受信")
                break

            # 進捗ログ（500グループごと）
            if i > 0 and i % 500 == 0:
                logger.info(f"グループ代表マージ進捗: {i:,} / {n:,} グループ処理中...")
                print(f"   >>> マージ進捗: {i:,} / {n:,} <<<")

            matched = False
            for rep_gid, rep_obj, merge_targets in merged:
                if self.img.is_same_image_obj(phash_obj, rep_obj):
                    merge_targets.append(gid)
                    matched = True
                    break
            if not matched:
                merged.append((gid, phash_obj, [gid]))

        # マージが発生したグループを DataManager に反映
        merged_count = 0
        for rep_gid, _, target_gids in merged:
            if len(target_gids) <= 1:
                continue  # マージなし → スキップ
            # マージ対象グループの全メンバーを収集
            all_members = []
            for tgid in target_gids:
                all_members.extend(groups[tgid]["members"])
            self.dm.assign_group(all_members, rep_gid)
            merged_count += 1

        # candidate 昇格（min_group_size=1 → 全件対象）
        self.dm.promote_candidates(min_group_size=1)

        logger.info(
            f"グループ代表マージ完了: {len(merged):,}グループ"
            f" ({merged_count}件マージ発生)"
        )
        print(f">>> マージ完了: {len(merged):,}グループ ({merged_count}件マージ) <<<\n")

    # ─────────────────────────────────────────────
    # pHash グループ化（min_group_size=1 でオーバーライド）
    # ─────────────────────────────────────────────

    def _run_phash_grouping(self):
        """
        pHash グループ化を実行。
        セラー分析では全商品を表示したいため min_group_size=1 に固定する。
        （キーワードリサーチの MIN_GROUP_SIZE=5 は適用しない）

        件数が MAX_PHASH_ITEMS を超える場合は image_processor 側で自動スキップされる。
        スキップ時はターミナルに「>>> pHash スキップ <<<」と表示される。
        """
        total = self.dm.total_items
        logger.info(f"=== pHash グループ化フェーズ開始: 対象 {total:,}件 ===")
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

    def _notify(self, index: int, status: str, extra: dict = None):
        """セラーごとの進捗をコールバックで通知。extra に追加情報を渡せる"""
        if self.on_seller_progress:
            try:
                self.on_seller_progress(index, status, extra or {})
            except Exception:
                pass
