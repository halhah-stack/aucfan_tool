"""
sellers_master.py - マスターセラーリスト管理

data/sellers_master.json を読み書きする。
STEP 1完了時に seller_id を追記、
STEP 3完了後に last_scraped_date / candidates_count を書き戻す。

データ構造:
[
  {
    "seller_id": "abc123",
    "first_seen_date": "2026-05-01",
    "last_scraped_date": null,
    "source_keyword": "バフ",
    "candidates_count": null
  }
]
"""
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# デフォルト保存パス
_DEFAULT_PATH = Path("data/sellers_master.json")


class SellersMaster:
    """マスターセラーリストの読み書きを担うクラス（スレッドセーフ）"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else _DEFAULT_PATH
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────
    # 内部 I/O
    # ──────────────────────────────────────────

    def _load(self) -> List[dict]:
        if not self.path.exists():
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"sellers_master.json 読み込みエラー: {e}")
            return []

    def _save(self, records: List[dict]):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"sellers_master.json 保存エラー: {e}")

    # ──────────────────────────────────────────
    # 公開 API
    # ──────────────────────────────────────────

    def upsert_sellers(self, seller_ids: List[str], source_keyword: str = ""):
        """
        seller_ids を追記（重複は first_seen_date を更新しない）。
        新規追加のみ行う。
        """
        if not seller_ids:
            return 0
        today = datetime.now().strftime("%Y-%m-%d")
        added = 0
        with self._lock:
            records = self._load()
            existing = {r["seller_id"] for r in records}
            for sid in seller_ids:
                if sid and sid not in existing:
                    records.append({
                        "seller_id": sid,
                        "first_seen_date": today,
                        "last_scraped_date": None,
                        "source_keyword": source_keyword,
                        "candidates_count": None,
                    })
                    existing.add(sid)
                    added += 1
            if added:
                self._save(records)
        logger.info(f"sellers_master: {added}件追加（合計 {len(records)}件）")
        return added

    def update_scraped(self, seller_id: str, candidates_count: Optional[int]):
        """STEP 3完了後に last_scraped_date と candidates_count を更新"""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            records = self._load()
            for r in records:
                if r["seller_id"] == seller_id:
                    r["last_scraped_date"] = today
                    r["candidates_count"] = candidates_count
                    break
            self._save(records)

    def get_all(self, sort_order: str = "desc") -> List[dict]:
        """全レコードを first_seen_date でソートして返す"""
        with self._lock:
            records = self._load()
        records.sort(
            key=lambda r: r.get("first_seen_date") or "",
            reverse=(sort_order == "desc"),
        )
        return records

    def get_unscraped(self, sort_order: str = "desc") -> List[dict]:
        """last_scraped_date が null のレコードのみ返す"""
        return [r for r in self.get_all(sort_order) if not r.get("last_scraped_date")]

    def get_last_modified(self) -> Optional[str]:
        """sellers_master.json の最終更新日時を文字列で返す（ファイル未存在時は None）"""
        if not self.path.exists():
            return None
        mtime = self.path.stat().st_mtime
        return datetime.fromtimestamp(mtime).strftime("%Y/%m/%d %H:%M")

    def stats(self) -> dict:
        """合計件数・未スクレイピング件数・最終更新日時を返す"""
        with self._lock:
            records = self._load()
        total = len(records)
        unscraped = sum(1 for r in records if not r.get("last_scraped_date"))
        return {
            "total": total,
            "unscraped": unscraped,
            "last_modified": self.get_last_modified(),
        }

    def clear_all(self) -> int:
        """全件削除（空配列にリセット）。削除前の件数を返す"""
        with self._lock:
            records = self._load()
            count = len(records)
            self._save([])
        logger.info(f"sellers_master: 全件削除（{count}件）")
        return count

    def delete_seller(self, seller_id: str) -> bool:
        """指定 seller_id を削除。削除できたら True を返す"""
        with self._lock:
            records = self._load()
            new_records = [r for r in records if r["seller_id"] != seller_id]
            if len(new_records) == len(records):
                return False
            self._save(new_records)
        logger.info(f"sellers_master: {seller_id} を削除")
        return True
