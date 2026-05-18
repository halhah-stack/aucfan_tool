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

import config

logger = logging.getLogger(__name__)

# デフォルト保存パス（Google Drive 未接続時はローカルにフォールバック）
def _resolve_default_path() -> Path:
    p = Path(config.SELLERS_MASTER_PATH)
    _gdrive_prefix = Path.home() / "Library" / "CloudStorage"
    if str(p).startswith(str(_gdrive_prefix)) and not _gdrive_prefix.exists():
        logger.warning("Google Drive が見つかりません。sellers_master をローカルにフォールバックします: data/sellers_master.json")
        return Path("data/sellers_master.json")
    return p

_DEFAULT_PATH = _resolve_default_path()


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

    def upsert_sellers(self, seller_ids: List[str], source_keyword: str = "",
                       seller_urls: dict = None):
        """
        seller_ids を追記（重複は first_seen_date を更新しない）。
        seller_urls: {seller_id: seller_url} の辞書（任意）。
          - 新規追加時は seller_url を保存する。
          - 既存レコードで seller_url が未設定の場合のみ更新する。
        """
        if not seller_ids:
            return 0
        seller_urls = seller_urls or {}
        today = datetime.now().strftime("%Y-%m-%d")
        added = 0
        with self._lock:
            records = self._load()
            existing = {r["seller_id"] for r in records}
            for sid in seller_ids:
                if not sid:
                    continue
                url = seller_urls.get(sid, "")
                if sid not in existing:
                    records.append({
                        "seller_id": sid,
                        "seller_url": url,
                        "first_seen_date": today,
                        "last_scraped_date": None,
                        "source_keyword": source_keyword,
                        "candidates_count": None,
                    })
                    existing.add(sid)
                    added += 1
                elif url:
                    # 既存レコードで seller_url が未設定の場合のみ更新
                    for r in records:
                        if r["seller_id"] == sid and not r.get("seller_url"):
                            r["seller_url"] = url
                            break
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

    def merge_from_file(self, import_path: str) -> dict:
        """
        外部の sellers_master.json をインポートしてマージする。
        seller_id で重複排除し、新しい ID だけを追加する。
        既存データは上書きしない（first_seen_date などを保持）。
        戻り値: {"added": N, "skipped": N, "total": N}
        """
        import_path = Path(import_path)
        if not import_path.exists():
            raise FileNotFoundError(f"インポートファイルが見つかりません: {import_path}")

        try:
            with open(import_path, encoding="utf-8") as f:
                import_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSONの解析に失敗しました: {e}")

        if not isinstance(import_data, list):
            raise ValueError("インポートファイルの形式が不正です（配列である必要があります）")

        added = 0
        skipped = 0

        with self._lock:
            records = self._load()
            existing = {r["seller_id"] for r in records}

            for item in import_data:
                if not isinstance(item, dict):
                    continue
                sid = item.get("seller_id", "").strip()
                if not sid:
                    continue
                if sid in existing:
                    skipped += 1
                else:
                    records.append({
                        "seller_id": sid,
                        "first_seen_date": item.get("first_seen_date"),
                        "last_scraped_date": item.get("last_scraped_date"),
                        "source_keyword": item.get("source_keyword", ""),
                        "candidates_count": item.get("candidates_count"),
                    })
                    existing.add(sid)
                    added += 1

            if added:
                self._save(records)

        total = len(records) if added else None
        if total is None:
            with self._lock:
                total = len(self._load())

        logger.info(f"sellers_master merge: {added}件追加、{skipped}件スキップ（合計 {total}件）")
        return {"added": added, "skipped": skipped, "total": total}
