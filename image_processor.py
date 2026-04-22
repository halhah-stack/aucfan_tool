"""
image_processor.py - 画像ダウンロード・pHash計算・同一商品グループ化
"""
import io
import os
import time
import uuid
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import imagehash
import requests
from PIL import Image

import config

logger = logging.getLogger(__name__)


class ImageProcessor:
    """
    画像処理クラス。
    - URLから画像ダウンロード
    - pHash計算
    - ハミング距離によるグループ化
    """

    def __init__(self, images_dir: Path):
        self.images_dir = images_dir
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })

    # ─────────────────────────────────────────────
    # 画像ダウンロード
    # ─────────────────────────────────────────────

    def download_image(self, url: str, prefix: str = "img") -> Optional[Path]:
        """
        URLから画像をダウンロードしてローカルに保存。
        成功時: 保存したファイルパスを返す
        失敗時: None を返す（例外はキャッチしてログ）
        """
        if not url or not url.startswith("http"):
            return None

        try:
            # URLからファイル名を生成（ハッシュで重複回避）
            url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
            ext = self._get_extension(url)
            filename = f"{prefix}_{url_hash}{ext}"
            save_path = self.images_dir / filename

            # すでにダウンロード済みならスキップ
            if save_path.exists() and save_path.stat().st_size > 100:
                return save_path

            resp = self._session.get(
                url,
                timeout=config.IMAGE_DOWNLOAD_TIMEOUT,
                stream=True
            )
            resp.raise_for_status()

            # 画像として読み込めるか確認
            img_data = resp.content
            img = Image.open(io.BytesIO(img_data))
            img.verify()  # 壊れた画像を除外

            # 再度開いて保存（verify後は再openが必要）
            img = Image.open(io.BytesIO(img_data))
            # RGB変換（PNG の透過チャンネルなどに対応）
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(save_path, format="JPEG", quality=85)

            logger.debug(f"画像DL成功: {filename}")
            return save_path

        except Exception as e:
            logger.warning(f"画像DL失敗 {url}: {e}")
            return None

    def download_images_batch(
        self, urls: List[str], prefix: str = "img"
    ) -> List[Optional[Path]]:
        """複数URLを順番にダウンロード"""
        results = []
        for url in urls:
            path = self.download_image(url, prefix=prefix)
            results.append(path)
        return results

    # ─────────────────────────────────────────────
    # pHash 計算
    # ─────────────────────────────────────────────

    def compute_phash(self, image_path: Path) -> Optional[str]:
        """
        pHash を計算して16進数文字列で返す。
        失敗時: None
        """
        try:
            img = Image.open(image_path)
            h = imagehash.phash(img)
            return str(h)
        except Exception as e:
            logger.warning(f"pHash計算失敗 {image_path}: {e}")
            return None

    def compute_phash_from_url(self, url: str, prefix: str = "thumb") -> Tuple[Optional[str], Optional[Path]]:
        """URLから直接pHashを計算（ダウンロードも行う）"""
        path = self.download_image(url, prefix=prefix)
        if path is None:
            return None, None
        phash_str = self.compute_phash(path)
        return phash_str, path

    def phash_distance(self, hash1_str: str, hash2_str: str) -> int:
        """2つのpHash文字列のハミング距離を返す"""
        try:
            h1 = imagehash.hex_to_hash(hash1_str)
            h2 = imagehash.hex_to_hash(hash2_str)
            return h1 - h2
        except Exception:
            return 999  # エラー時は別物とみなす

    def is_same_image(self, hash1_str: str, hash2_str: str) -> bool:
        """pHash距離が閾値以内なら同一画像と判定"""
        if not hash1_str or not hash2_str:
            return False
        dist = self.phash_distance(hash1_str, hash2_str)
        return dist <= config.PHASH_THRESHOLD

    # ─────────────────────────────────────────────
    # グループ化（Union-Find ベース）
    # ─────────────────────────────────────────────

    def group_by_phash(
        self, items: List[dict]
    ) -> Dict[str, List[str]]:
        """
        pHashが近い商品を同一グループにまとめる。
        Union-Find アルゴリズムを使用（複数ページをまたいで判定）。

        Args:
            items: item_id と phash を持つ辞書のリスト

        Returns:
            {group_id: [item_id, ...]} の辞書
        """
        # pHash がある商品のみ対象
        valid = [(item["item_id"], item["phash"]) for item in items if item.get("phash")]
        n = len(valid)

        if n == 0:
            return {}

        # Union-Find 初期化
        parent = {item_id: item_id for item_id, _ in valid}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]  # path compression
                x = parent[x]
            return x

        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx

        # O(n²) でハミング距離を計算してマージ
        # 500ページ × 50件 = 最大25,000件だが、候補は絞られているので現実的
        logger.info(f"pHashグループ化開始: {n}件")
        for i in range(n):
            id1, h1 = valid[i]
            for j in range(i + 1, n):
                id2, h2 = valid[j]
                if self.is_same_image(h1, h2):
                    union(id1, id2)

        # グループをまとめる
        groups: Dict[str, List[str]] = {}
        for item_id, _ in valid:
            root = find(item_id)
            groups.setdefault(root, []).append(item_id)

        logger.info(f"pHashグループ化完了: {len(groups)}グループ")
        return groups

    def group_items(self, data_manager) -> int:
        """
        DataManager のアイテムを pHash でグループ化し、
        DataManager に反映する。
        変更したグループ数を返す。
        """
        items = data_manager.get_all_items()
        groups = self.group_by_phash(items)

        count = 0
        for group_root, member_ids in groups.items():
            # group_id は最初のメンバーのIDを使用
            gid = group_root
            data_manager.assign_group(member_ids, gid)
            count += 1

        # グループサイズ閾値以上を候補に昇格
        data_manager.promote_candidates()
        return count

    # ─────────────────────────────────────────────
    # ユーティリティ
    # ─────────────────────────────────────────────

    def _get_extension(self, url: str) -> str:
        """URLから拡張子を推定"""
        try:
            path = urlparse(url).path.lower()
            for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                if path.endswith(ext):
                    return ".jpg" if ext in (".jpg", ".jpeg", ".webp") else ext
        except Exception:
            pass
        return ".jpg"

    def get_image_url_path(self, local_path: Optional[Path]) -> str:
        """ローカルパスを Flask で配信できる相対パスに変換"""
        if local_path is None:
            return ""
        return f"/images/{local_path.name}"

    def cleanup_broken_images(self):
        """壊れた画像ファイルを削除"""
        removed = 0
        for f in self.images_dir.glob("*.jpg"):
            try:
                img = Image.open(f)
                img.verify()
            except Exception:
                f.unlink()
                removed += 1
        if removed > 0:
            logger.info(f"壊れた画像を {removed} 件削除しました")
