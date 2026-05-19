"""
setup_gdrive_auth.py — Google Drive API 初回認証スクリプト

【実行方法】（初回のみ）
  cd ~/Downloads/aucfan_tool
  source .venv/bin/activate
  python setup_gdrive_auth.py

【前提条件】
  - Google Cloud Console で OAuth2 クライアント ID を作成済みであること
  - 作成した認証情報を credentials.json として aucfan_tool フォルダに保存済みであること

【手順（未作成の場合）】
  1. https://console.cloud.google.com/ を開く
  2. 「APIとサービス」→「ライブラリ」→「Google Drive API」を有効化
  3. 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuth 2.0 クライアント ID」
     アプリケーションの種類: 「デスクトップアプリ」を選択 → 作成
  4. ダウンロードボタンで JSON を保存 → aucfan_tool/credentials.json にリネーム
  5. このスクリプトを実行 → ブラウザが開くので Google アカウントでログイン → 許可
  6. token.json が生成されたら完了。以後は自動更新される。
"""

from pathlib import Path

BASE_DIR = Path(__file__).parent
CREDENTIALS_PATH = BASE_DIR / "credentials.json"
TOKEN_PATH = BASE_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]


def main():
    print("=" * 60)
    print("Google Drive API 認証セットアップ")
    print("=" * 60)

    # credentials.json の存在確認
    if not CREDENTIALS_PATH.exists():
        print(f"\n❌ credentials.json が見つかりません。")
        print(f"   配置先: {CREDENTIALS_PATH}")
        print()
        print("【取得手順】")
        print("  1. https://console.cloud.google.com/ を開く")
        print("  2. 「APIとサービス」→「ライブラリ」→「Google Drive API」を有効化")
        print("  3. 「APIとサービス」→「認証情報」→「認証情報を作成」")
        print("     →「OAuth 2.0 クライアント ID」")
        print("     アプリケーションの種類:「デスクトップアプリ」→ 作成")
        print("  4. JSONをダウンロード → credentials.json として上記パスに保存")
        print("  5. このスクリプトを再実行")
        return

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("\n❌ 必要なパッケージが未インストールです。以下を実行してください:")
        print("   pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
        return

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        print("\n✅ 認証済みトークンが既に存在します。")
        print(f"   {TOKEN_PATH}")
        print("\n再認証する場合は token.json を削除して再実行してください。")
        return

    if creds and creds.expired and creds.refresh_token:
        print("\n🔄 トークンを更新中...")
        creds.refresh(Request())
        print("✅ トークン更新完了。")
    else:
        print("\nブラウザが開きます。Google アカウントでログインして許可してください...")
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"\n✅ 認証完了！token.json を保存しました。")
    print(f"   {TOKEN_PATH}")
    print("\nこれ以降は自動的にトークンが更新されます。")

    # 動作確認
    print("\n動作確認中...")
    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=creds)
        about = service.about().get(fields="user").execute()
        email = about.get("user", {}).get("emailAddress", "不明")
        print(f"✅ Google Drive に接続できました。アカウント: {email}")
    except Exception as e:
        print(f"⚠️  接続確認でエラー: {e}")
        print("   認証自体は完了しているため、ツール起動で再確認してください。")


if __name__ == "__main__":
    main()
