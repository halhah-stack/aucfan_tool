"""
gdrive_uploader.py — Google Drive API 直接アップロードモジュール

【概要】
  ストリーミングモードの GDrive では shutil.copy2 が機能しないため、
  Google Drive API を使って直接アップロードする。

【初回セットアップ手順】
  1. Google Cloud Console (https://console.cloud.google.com/) でプロジェクトを開く
     （Gemini で使っているプロジェクトを流用可能）
  2. 「APIとサービス」→「ライブラリ」→「Google Drive API」を有効化
  3. 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuth 2.0 クライアント ID」
     アプリケーションの種類: 「デスクトップアプリ」を選択
  4. ダウンロードした JSON を aucfan_tool フォルダ内に credentials.json として保存
  5. ターミナルで以下を実行（初回のみ）:
       cd ~/Downloads/aucfan_tool
       source .venv/bin/activate
       python setup_gdrive_auth.py
  6. ブラウザが開くので Google アカウントでログイン → 許可
  7. token.json が生成されたら完了。以後は自動更新される。
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/drive"]
_BASE_DIR = Path(__file__).parent
TOKEN_PATH = _BASE_DIR / "token.json"
CREDENTIALS_PATH = _BASE_DIR / "credentials.json"

# モジュールレベルキャッシュ（Flask の 1 プロセス内で共有）
_service = None
_folder_cache: dict = {}  # "parent_id/name" → folder_id


# ─────────────────────────────────────────────
# Drive サービス取得
# ─────────────────────────────────────────────

def get_drive_service():
    """
    Drive API サービスオブジェクトを返す（シングルトン）。
    credentials.json が存在しない場合や認証失敗時は None を返す。
    """
    global _service
    if _service is not None:
        return _service

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        logger.error(
            "Google Drive API ライブラリが未インストールです。\n"
            "  pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )
        return None

    if not CREDENTIALS_PATH.exists():
        logger.warning(
            f"credentials.json が見つかりません: {CREDENTIALS_PATH}\n"
            "  Google Cloud Console から OAuth2 認証情報をダウンロードして配置してください。"
        )
        return None

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # トークンが無効または期限切れなら再取得
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
            except Exception as e:
                logger.warning(f"トークンリフレッシュ失敗: {e}")
                return None
        else:
            # token.json がない = 初回認証が必要
            logger.warning(
                "GDrive 認証トークンがありません。\n"
                "  python setup_gdrive_auth.py を実行して初回認証を完了してください。"
            )
            return None

    _service = build("drive", "v3", credentials=creds)
    logger.info("Google Drive API サービス初期化完了")
    return _service


# ─────────────────────────────────────────────
# フォルダ操作
# ─────────────────────────────────────────────

def get_or_create_folder(name: str, parent_id: str) -> Optional[str]:
    """
    parent_id 配下に name フォルダを取得または作成してフォルダ ID を返す。
    失敗時は None。
    """
    cache_key = f"{parent_id}/{name}"
    if cache_key in _folder_cache:
        return _folder_cache[cache_key]

    service = get_drive_service()
    if service is None:
        return None

    try:
        # 既存フォルダを検索
        safe_name = name.replace("'", "\\'")
        query = (
            f"name='{safe_name}' and "
            f"'{parent_id}' in parents and "
            f"mimeType='application/vnd.google-apps.folder' and "
            f"trashed=false"
        )
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])

        if files:
            folder_id = files[0]["id"]
            logger.debug(f"GDriveフォルダ既存: {name} ({folder_id})")
        else:
            # 新規作成
            metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            folder = service.files().create(body=metadata, fields="id").execute()
            folder_id = folder["id"]
            logger.info(f"GDriveフォルダ作成: {name} ({folder_id})")

        _folder_cache[cache_key] = folder_id
        return folder_id

    except Exception as e:
        logger.warning(f"GDriveフォルダ操作失敗 ({name}): {e}")
        return None


def get_or_create_folder_path(path_parts: list, root_id: str = "root") -> Optional[str]:
    """
    パスリストを再帰的にたどってフォルダ ID を返す。
    存在しないフォルダは途中で作成する。

    例:
      get_or_create_folder_path(["AucFanToolData", "リサーチ結果", "session_xxx", "images"])
    """
    current_id = root_id
    for part in path_parts:
        current_id = get_or_create_folder(part, current_id)
        if current_id is None:
            logger.warning(f"フォルダパス解決失敗: {'/'.join(path_parts)} ('{part}' で停止)")
            return None
    return current_id


# ─────────────────────────────────────────────
# ファイルアップロード
# ─────────────────────────────────────────────

def upload_file(local_path: Path, folder_id: str, filename: str) -> bool:
    """
    local_path のファイルを GDrive の folder_id にアップロードする。
    同名ファイルが既に存在する場合はスキップ（True を返す）。
    失敗時は False を返す（例外はキャッチしてログ出力）。
    """
    service = get_drive_service()
    if service is None:
        return False

    try:
        from googleapiclient.http import MediaFileUpload

        # 同名ファイルが既存かチェック
        safe_name = filename.replace("'", "\\'")
        query = f"name='{safe_name}' and '{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields="files(id)").execute()
        if results.get("files"):
            logger.debug(f"GDrive既存スキップ: {filename}")
            return True

        # アップロード
        media = MediaFileUpload(str(local_path), mimetype="image/jpeg", resumable=False)
        metadata = {"name": filename, "parents": [folder_id]}
        service.files().create(body=metadata, media_body=media, fields="id").execute()
        logger.debug(f"GDriveアップロード完了: {filename}")
        return True

    except Exception as e:
        logger.warning(f"GDriveアップロード失敗 ({filename}): {e}")
        return False


# ─────────────────────────────────────────────
# キャッシュリセット（セッション削除時などに呼ぶ）
# ─────────────────────────────────────────────

def clear_folder_cache():
    """フォルダ ID キャッシュをリセットする"""
    global _folder_cache
    _folder_cache = {}
    logger.debug("GDrive フォルダキャッシュをリセットしました")
