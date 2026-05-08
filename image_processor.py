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
import time as _time

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

        【現在の方式】代表ハッシュ比較方式（2025-05-03 変更）
          各アイテムをグループ先頭の「代表ハッシュ」とのみ比較する。
          A≒B≒C でも A と C が遠ければ別グループになる（連鎖を防ぐ）。
          閾値は .env の PHASH_THRESHOLD で調整（デフォルト 2）。

        【元の方式に戻す場合】Union-Find方式
          この関数を git で以下のコミットに戻す:
            git checkout ac1661c -- image_processor.py
          または PHASH_THRESHOLD=0 にすると実質的に完全一致のみになる。

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

        # 件数が上限を超えた場合は pHash グループ化をスキップ
        # （超えると比較回数が爆発的に増えてフリーズする恐れがあるため）
        if n > config.MAX_PHASH_ITEMS:
            logger.warning(
                f"pHashグループ化スキップ: {n}件 > 上限{config.MAX_PHASH_ITEMS}件。"
                f"各アイテムを個別グループとして扱います。"
                f"上限を上げたい場合は .env の MAX_PHASH_ITEMS を変更してください。"
            )
            return {item_id: [item_id] for item_id, _ in valid}

        logger.info(f"pHashグループ化開始: {n}件 (閾値={config.PHASH_THRESHOLD})")

        # 代表ハッシュ比較方式
        # groups: [(代表hash, [item_id, ...])]
        # ※元のUnion-Find方式に戻すには上記docstringを参照
        groups: List[Tuple[str, List[str]]] = []

        # GIL解放インターバル: 500件ごとに sleep(0) してFlask等の他スレッドに制御を渡す
        # pHash比較は純粋Python計算でGILを保持し続けるため、これがないとFlaskが応答不能になる
        _GIL_YIELD_INTERVAL = 500

        for i, (item_id, item_hash) in enumerate(valid):
            # 定期的にGILを解放（他スレッドにCPU時間を渡す）
            if i % _GIL_YIELD_INTERVAL == 0 and i > 0:
                _time.sleep(0)
                logger.debug(f"pHashグループ化: {i}/{n}件処理中 ({len(groups)}グループ)")

            matched = False
            for rep_hash, members in groups:
                if self.is_same_image(item_hash, rep_hash):
                    members.append(item_id)
                    matched = True
                    break
            if not matched:
                # 新グループ作成（このアイテムが代表ハッシュになる）
                groups.append((item_hash, [item_id]))

        result = {members[0]: members for _, members in groups}
        logger.info(f"pHashグループ化完了: {len(result)}グループ")
        return result

    def group_items(self, data_manager) -> int:
        """
        DataManager のアイテムを pHash でグループ化し、
        DataManager に反映する。
        変更したグループ数を返す。
        """
        return self.group_items_with_min_size(data_manager, min_group_size=None)

    def group_items_with_min_size(self, data_manager, min_group_size: int = None) -> int:
        """
        DataManager のアイテムを pHash でグループ化し、DataManager に反映する。
        min_group_size を指定すると promote_candidates の閾値を上書きできる。
        （セラー分析では min_group_size=1 を渡して全商品を候補にする）
        """
        items = data_manager.get_all_items()
        groups = self.group_by_phash(items)

        count = 0
        for group_root, member_ids in groups.items():
            gid = group_root
            data_manager.assign_group(member_ids, gid)
            count += 1

        # グループサイズ閾値以上を候補に昇格
        data_manager.promote_candidates(min_group_size=min_group_size)
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
