"""
SP-API Refresh Token 取得スクリプト
一度だけ実行してRefresh Tokenを取得する。取得後はこのファイルを削除してください。

使い方:
    cd ~/Downloads/aucfan_tool
    python3 get_refresh_token.py
"""

import urllib.parse
import urllib.request
import json
import webbrowser

# ── 設定（.envから読み込む） ──────────────────────────────────
import os
from dotenv import load_dotenv
load_dotenv()
CLIENT_ID     = os.getenv("SP_API_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SP_API_CLIENT_SECRET", "")
APP_ID        = os.getenv("SP_API_APP_ID", "amzn1.sp.solution.4341a5d5-fc50-42b5-b0b3-ff3414de98d0")
REDIRECT_URI  = "http://localhost:5001/callback"
# ─────────────────────────────────────────────────────────────

def main():
    # 1. 認証URLを生成してブラウザで開く
    auth_url = (
        f"https://sellercentral-japan.amazon.com/apps/authorize/consent"
        f"?application_id={APP_ID}"
        f"&state=mystate"
        f"&version=beta"
    )
    print("=" * 60)
    print("ブラウザで以下のURLを開きます...")
    print(auth_url)
    print("=" * 60)
    webbrowser.open(auth_url)

    # 2. リダイレクト後のURLを貼り付けてもらう
    print("\nAmazonで「許可」をクリックすると、URLが変わります。")
    print("変わった後のURLをそのままコピーして貼り付けてください:")
    redirect_url = input("> ").strip()

    # 3. URLからspapi_oauth_codeを抽出
    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)
    if "spapi_oauth_code" not in params:
        # URLではなくcodeだけ貼った場合
        code = redirect_url
    else:
        code = params["spapi_oauth_code"][0]
    print(f"\n認証コード: {code}")

    # 4. Refresh Tokenと交換
    token_url = "https://api.amazon.com/auth/o2/token"
    data = urllib.parse.urlencode({
        "grant_type":   "authorization_code",
        "code":         code,
        "redirect_uri": REDIRECT_URI,
        "client_id":    CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()

    req = urllib.request.Request(token_url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as res:
            result = json.loads(res.read())
    except urllib.error.HTTPError as e:
        print(f"\nエラー: {e.read().decode()}")
        return

    refresh_token = result.get("refresh_token")
    if refresh_token:
        print("\n" + "=" * 60)
        print("✅ Refresh Token 取得成功！")
        print("以下を ~/Downloads/aucfan_tool/.env に追加してください:")
        print("=" * 60)
        print(f"SP_API_CLIENT_ID={CLIENT_ID}")
        print(f"SP_API_CLIENT_SECRET={CLIENT_SECRET}")
        print(f"SP_API_REFRESH_TOKEN={refresh_token}")
        print(f"SP_API_MARKETPLACE_ID=A1VC38T7YXB528")
        print("=" * 60)
        print("\n⚠️ このスクリプトは削除してください: rm get_refresh_token.py")
    else:
        print(f"\n取得失敗: {result}")

if __name__ == "__main__":
    main()
