"""
upload_s2_images.py — img_cache/ の画像をGoogle Driveに一括アップロード

【使い方】
  cd ~/Downloads/aucfan_tool
  source .venv/bin/activate
  python upload_s2_images.py

【特徴】
  - GDriveのフォルダ内ファイル一覧を一括取得して差分のみアップロード（高速）
  - S2_* セッションのみ対象（S2_ONLY=True の場合）
  - GDrive構成: AucFanToolData/リサーチ結果/{セッション名}/images/{ファイル名}
"""

import sys
import time
import logging
from pathlib import Path

# ログ設定
logging.basicConfig(
    level=logging.WARNING,  # gdrive_uploaderの細かいログを抑制
    format="[%(asctime)s] %(levelname)s:  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────

# アップロード元（ローカルimg_cacheフォルダ）
IMG_CACHE_DIR = Path(__file__).parent / "img_cache"

# S2セッションのみ対象にする場合は True、全セッション（S1/S2/S3）は False
S2_ONLY = False

# GDrive上の格納先パス
GDRIVE_ROOT_PATH = ["AucFanToolData", "リサーチ結果"]


# ─────────────────────────────────────────────
# GDriveフォルダ内ファイル名を一括取得
# ─────────────────────────────────────────────

def list_gdrive_filenames(service, folder_id: str) -> set:
    """
    folder_id 配下のファイル名をすべて取得してセットで返す。
    ページネーション対応。
    """
    names = set()
    page_token = None
    query = f"'{folder_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'"
    while True:
        params = dict(q=query, fields="nextPageToken, files(name)", pageSize=1000)
        if page_token:
            params["pageToken"] = page_token
        result = service.files().list(**params).execute()
        for f in result.get("files", []):
            names.add(f["name"])
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return names


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────

def main():
    try:
        import gdrive_uploader
    except ImportError:
        print("ERROR: gdrive_uploader.py が見つかりません。aucfan_toolフォルダで実行してください。")
        sys.exit(1)

    # Drive接続確認
    service = gdrive_uploader.get_drive_service()
    if service is None:
        print("ERROR: Google Drive API に接続できません。setup_gdrive_auth.py を実行してください。")
        sys.exit(1)

    print(f"[{time.strftime('%H:%M:%S')}] INFO:  Google Drive API 接続OK")

    if not IMG_CACHE_DIR.exists():
        print(f"ERROR: img_cacheフォルダが見つかりません: {IMG_CACHE_DIR}")
        sys.exit(1)

    # 対象セッションフォルダを収集
    sessions = sorted([
        d for d in IMG_CACHE_DIR.iterdir()
        if d.is_dir() and (not S2_ONLY or d.name.startswith("S2_"))
    ])

    if not sessions:
        print("対象セッションフォルダが見つかりません。")
        return

    print(f"[{time.strftime('%H:%M:%S')}] INFO:  対象セッション: {len(sessions)}件")

    total_upload = 0
    total_skip = 0
    total_fail = 0
    start = time.time()

    for session_dir in sessions:
        local_images = sorted([
            f for f in session_dir.rglob("*")
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
        ])
        local_count = len(local_images)

        # GDriveフォルダID取得/作成
        folder_id = gdrive_uploader.get_or_create_folder_path(
            GDRIVE_ROOT_PATH + [session_dir.name, "images"]
        )
        if folder_id is None:
            print(f"[{time.strftime('%H:%M:%S')}] ERROR: フォルダID取得失敗 → {session_dir.name}")
            total_fail += local_count
            continue

        # GDrive側のファイル名を一括取得
        print(f"[{time.strftime('%H:%M:%S')}] INFO:  {session_dir.name}: GDriveファイル一覧取得中...", flush=True)
        gdrive_names = list_gdrive_filenames(service, folder_id)

        # 差分（未アップロード）を抽出
        missing = [f for f in local_images if f.name not in gdrive_names]
        skip_count = local_count - len(missing)

        print(
            f"[{time.strftime('%H:%M:%S')}] INFO:  {session_dir.name}: "
            f"ローカル {local_count:,}枚 / GDrive済み {skip_count:,}枚 / 未アップロード {len(missing):,}枚"
        )
        total_skip += skip_count

        if not missing:
            continue

        # 差分のみアップロード
        s_ok = s_fail = 0
        for i, img_path in enumerate(missing, 1):
            ok = gdrive_uploader.upload_file(
                local_path=img_path,
                folder_id=folder_id,
                filename=img_path.name,
            )
            if ok:
                s_ok += 1
                total_upload += 1
            else:
                s_fail += 1
                total_fail += 1

            # 進捗表示（100枚ごと）
            if i % 100 == 0 or i == len(missing):
                elapsed = time.time() - start
                rate = (total_upload + total_fail) / elapsed if elapsed > 0 else 0
                eta = (len(missing) - i) / (i / elapsed) if elapsed > 0 and i > 0 else 0
                print(
                    f"[{time.strftime('%H:%M:%S')}] INFO:  "
                    f"  [{i:,}/{len(missing):,}] {i*100//len(missing)}%"
                    f"  成功:{s_ok:,}  失敗:{s_fail:,}"
                    f"  残り約{eta/60:.0f}分",
                    flush=True,
                )

    elapsed = time.time() - start
    print()
    print(
        f"[{time.strftime('%H:%M:%S')}] INFO:  完了: "
        f"アップロード={total_upload:,}  スキップ={total_skip:,}  失敗={total_fail:,}  "
        f"所要時間={elapsed/60:.1f}分"
    )


if __name__ == "__main__":
    main()
