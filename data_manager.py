"""
data_manager.py - データ管理・CSV保存・進捗保存・再開機能
"""
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

import config


class DataManager:
    """
    スクレイピングデータの管理クラス。
    - items: 全商品データをメモリで保持（スレッドセーフ）
    - progress: スクレイピング進捗を保持
    - CSV・JSONへの自動保存
    - 途中再開機能
    """

    def __init__(self, session_id: str, output_dir: Path):
        self.session_id = session_id
        self.output_dir = output_dir
        self.images_dir = output_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()

        # 商品データ辞書 {item_id: item_dict}
        self._items: Dict[str, dict] = {}

        # 進捗データ
        self._progress = {
            "session_id": session_id,
            "started_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "idle",           # idle / scraping_list / scraping_detail / done / stopped
            "keyword": "",
            "current_url": "",
            "pages_done": 0,
            "total_pages": 0,
            "total_items": 0,
            "candidates_found": 0,
            "detail_pages_done": 0,
            "detail_pages_total": 0,
            "detail_done_urls": [],     # 詳細取得済みURL リスト
            "errors": [],               # エラーログ
        }

        # ファイルパス
        self._progress_file = output_dir / "progress.json"
        self._csv_file = output_dir / "results.csv"
        self._items_file = output_dir / "items.json"

    # ─────────────────────────────────────────────
    # 保存・ロード
    # ─────────────────────────────────────────────

    def save_progress(self):
        """進捗をJSONに保存（エラーでも止まらない）"""
        try:
            with self._lock:
                self._progress["updated_at"] = datetime.now().isoformat()
                data = dict(self._progress)
            with open(self._progress_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[DataManager] 進捗保存エラー: {e}")

    def save_items(self):
        """商品データをJSONに保存"""
        try:
            with self._lock:
                items_copy = dict(self._items)
            with open(self._items_file, "w", encoding="utf-8") as f:
                json.dump(items_copy, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[DataManager] アイテム保存エラー: {e}")

    def save_csv(self):
        """CSVに保存"""
        try:
            with self._lock:
                items_list = list(self._items.values())
            if not items_list:
                return
            df = pd.DataFrame(items_list)
            # 列順序
            cols = [
                "item_id", "keyword", "status", "group_id", "group_size",
                "title_short", "title_full",
                "price", "shipping", "total",
                "seller_id", "url",
                "thumbnail_local", "images_local",
                "phash", "needs_review", "exclude_reason",
                "scraped_detail",
            ]
            existing_cols = [c for c in cols if c in df.columns]
            df = df[existing_cols + [c for c in df.columns if c not in existing_cols]]
            df.to_csv(self._csv_file, index=False, encoding="utf-8-sig")
        except Exception as e:
            print(f"[DataManager] CSV保存エラー: {e}")

    def save_all(self):
        """全データを保存"""
        self.save_progress()
        self.save_items()
        self.save_csv()

    def load_previous_session(self) -> bool:
        """
        前回セッションのデータをロード。
        戻り値: ロードに成功したら True
        """
        if not self._progress_file.exists() or not self._items_file.exists():
            return False
        try:
            with open(self._progress_file, "r", encoding="utf-8") as f:
                prev_progress = json.load(f)
            with open(self._items_file, "r", encoding="utf-8") as f:
                prev_items = json.load(f)

            with self._lock:
                self._progress.update(prev_progress)
                self._items = prev_items

            print(f"[DataManager] 前回セッションを再開: {len(prev_items)}件ロード済み")
            return True
        except Exception as e:
            print(f"[DataManager] 前回セッションロードエラー: {e}")
            return False

    # ─────────────────────────────────────────────
    # 商品データ操作
    # ─────────────────────────────────────────────

    def add_item(self, item: dict) -> str:
        """商品を追加。item_id を返す"""
        with self._lock:
            item_id = item.get("item_id") or str(uuid.uuid4())
            item["item_id"] = item_id
            item.setdefault("status", config.STATUS_WAITING)
            item.setdefault("scraped_detail", False)
            item.setdefault("group_id", None)
            item.setdefault("group_size", 1)
            item.setdefault("needs_review", False)
            item.setdefault("exclude_reason", "")
            item.setdefault("title_full", "")
            item.setdefault("shipping", 0)
            item.setdefault("total", item.get("price", 0))
            item.setdefault("images_local", [])
            item.setdefault("phash", "")
            item.setdefault("seller_url", "")  # a.sellerLink の href（セラー分析機能で使用）
            self._items[item_id] = item
        return item_id

    def update_item(self, item_id: str, updates: dict):
        """商品データを部分更新"""
        with self._lock:
            if item_id in self._items:
                self._items[item_id].update(updates)

    def get_item(self, item_id: str) -> Optional[dict]:
        with self._lock:
            return dict(self._items.get(item_id, {}))

    def get_all_items(self) -> List[dict]:
        with self._lock:
            return [dict(v) for v in self._items.values()]

    def get_items_filtered(
        self,
        keyword: str = "",
        status: str = "",
        min_price: int = 0,
        max_price: int = 999999,
        min_group: int = 0,
    ) -> List[dict]:
        """フィルタリングした商品リストを返す"""
        with self._lock:
            items = list(self._items.values())

        result = []
        for item in items:
            if keyword and keyword not in item.get("keyword", "") and keyword not in item.get("title_short", ""):
                continue
            if status and item.get("status") != status:
                continue
            total = item.get("total", 0)
            if total < min_price or total > max_price:
                continue
            if item.get("group_size", 1) < min_group:
                continue
            result.append(item)
        return result

    def get_groups(self) -> Dict[str, List[dict]]:
        """グループID別に商品をまとめて返す"""
        with self._lock:
            items = list(self._items.values())
        groups: Dict[str, List[dict]] = {}
        ungrouped = []
        for item in items:
            gid = item.get("group_id")
            if gid:
                groups.setdefault(gid, []).append(item)
            else:
                ungrouped.append(item)
        # グループなし商品は個別グループとして扱う
        for item in ungrouped:
            groups[item["item_id"]] = [item]
        return groups

    def get_unscraped_candidates(self) -> List[dict]:
        """詳細ページ未取得の候補商品を返す"""
        with self._lock:
            return [
                dict(v) for v in self._items.values()
                if not v.get("scraped_detail", False)
                and v.get("status") not in (config.STATUS_NG,)
            ]

    def get_items_without_phash(self) -> List[dict]:
        """pHash未計算の商品を返す"""
        with self._lock:
            return [dict(v) for v in self._items.values() if not v.get("phash")]

    def update_status(self, item_id: str, status: str):
        """ステータスを更新"""
        self.update_item(item_id, {"status": status})

    def assign_group(self, item_ids: List[str], group_id: str):
        """商品グループを割り当て"""
        size = len(item_ids)
        with self._lock:
            for item_id in item_ids:
                if item_id in self._items:
                    self._items[item_id]["group_id"] = group_id
                    self._items[item_id]["group_size"] = size

    def promote_candidates(self, min_group_size: int = None):
        """
        グループサイズに応じて商品ステータスを昇格する。

        - size >= threshold (MIN_GROUP_SIZE)          → candidate（仕入れ候補）
        - size >= next_threshold (MIN_NEXT_CANDIDATE_SIZE) → next_candidate（次期候補）
        - それ未満                                    → waiting のまま

        min_group_size=1（セラー分析）の場合は全商品が candidate になるため
        next_candidate の elif は自然にスキップされる。
        """
        threshold = min_group_size if min_group_size is not None else config.MIN_GROUP_SIZE
        next_threshold = config.MIN_NEXT_CANDIDATE_SIZE
        groups = self.get_groups()
        with self._lock:
            for gid, members in groups.items():
                size = len(members)
                if size >= threshold:
                    for item in members:
                        iid = item["item_id"]
                        if self._items[iid]["status"] == config.STATUS_WAITING:
                            self._items[iid]["status"] = config.STATUS_CANDIDATE
                elif size >= next_threshold:
                    for item in members:
                        iid = item["item_id"]
                        if self._items[iid]["status"] == config.STATUS_WAITING:
                            self._items[iid]["status"] = config.STATUS_NEXT_CANDIDATE

    def add_error(self, msg: str):
        with self._lock:
            self._progress["errors"].append({
                "time": datetime.now().isoformat(),
                "msg": msg,
            })
            # エラーリストは最大200件
            if len(self._progress["errors"]) > 200:
                self._progress["errors"] = self._progress["errors"][-200:]

    # ─────────────────────────────────────────────
    # 進捗データ操作
    # ─────────────────────────────────────────────

    def update_progress(self, **kwargs):
        with self._lock:
            self._progress.update(kwargs)
            self._progress["updated_at"] = datetime.now().isoformat()

    def get_progress(self) -> dict:
        with self._lock:
            return dict(self._progress)

    def mark_detail_done(self, url: str):
        with self._lock:
            if url not in self._progress["detail_done_urls"]:
                self._progress["detail_done_urls"].append(url)

    def is_detail_done(self, url: str) -> bool:
        with self._lock:
            return url in self._progress["detail_done_urls"]

    def export_csv(self, filepath: Optional[Path] = None) -> Path:
        """CSVエクスポート（引数がなければ results.csv に保存）"""
        target = filepath or self._csv_file
        self.save_csv()
        return target

    # ─────────────────────────────────────────────
    # ユーティリティ
    # ─────────────────────────────────────────────

    @property
    def total_items(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def candidate_count(self) -> int:
        with self._lock:
            return sum(
                1 for v in self._items.values()
                if v.get("status") == config.STATUS_CANDIDATE
            )

    def get_stats(self) -> dict:
        """
        統計情報を返す。
        - total: 取得アイテム総数（件数ベース）
        - by_status: グループ単位のステータス集計
            ※ 同一商品20件グループは「1候補」としてカウント
            【元に戻す場合】グループ単位→アイテム単位に変更:
              statuses = {}
              for v in self._items.values():
                  s = v.get("status", "unknown")
                  statuses[s] = statuses.get(s, 0) + 1
        """
        with self._lock:
            items = list(self._items.values())

        # グループ単位でステータスを集計（代表アイテム = group_id が最初に出現した1件）
        seen_groups: dict = {}  # group_id -> status
        for item in items:
            gid = item.get("group_id") or item["item_id"]
            if gid not in seen_groups:
                seen_groups[gid] = item.get("status", "unknown")

        group_statuses: dict = {}
        for status in seen_groups.values():
            group_statuses[status] = group_statuses.get(status, 0) + 1

        return {
            "total": len(items),          # 取得件数（アイテム総数）
            "total_groups": len(seen_groups),  # グループ総数
            "by_status": group_statuses,  # グループ単位のステータス集計
        }


# ─────────────────────────────────────────────
# セッションID生成ユーティリティ
# ─────────────────────────────────────────────

def make_session_id(keyword: str) -> str:
    """後方互換のため保持。新コードは make_output_dir(step=) を直接呼ぶこと。"""
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_kw = "".join(c for c in keyword if c.isalnum() or c in ("_", "-"))[:20]
    return f"{safe_kw}_{date_str}"


def make_output_dir(keyword: str, step: int = 1) -> tuple:
    """
    新命名規則でセッションフォルダを作成して (out_dir, session_id) を返す。

      step=1: リサーチ結果/S1_YYYYMMDD_NN_keyword/
      step=2: リサーチ結果/S2_YYYYMMDD_NN/
      step=3: リサーチ結果/S3_YYYYMMDD_NN/

    NN は同日・同ステップの通番（01, 02, ...）。
    旧フォルダ（keyword_YYYYMMDD_HHMMSS 形式）は後方互換として読み込めるが、
    新規作成は常に新命名規則を使う。
    """
    import re as _re

    date_str = datetime.now().strftime("%Y%m%d")
    step_prefix = f"S{step}_{date_str}_"
    base = Path(config.OUTPUT_BASE_DIR)
    base.mkdir(parents=True, exist_ok=True)

    # 通番: 同日・同ステップの既存フォルダ中の最大番号 + 1
    try:
        existing_nums = []
        for d in base.iterdir():
            if d.is_dir() and d.name.startswith(step_prefix):
                m = _re.match(rf'^S{step}_\d{{8}}_(\d+)', d.name)
                if m:
                    existing_nums.append(int(m.group(1)))
        num = max(existing_nums, default=0) + 1
    except Exception:
        num = 1

    if step == 1:
        # OS で使えない文字を除去してキーワードをフォルダ名に含める
        safe_kw = _re.sub(r'[/\\:*?"<>|\t\n\r]', '', keyword).strip()[:15]
        session_id = f"S1_{date_str}_{num:02d}_{safe_kw}"
    else:
        session_id = f"S{step}_{date_str}_{num:02d}"

    out_dir = base / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir, session_id
