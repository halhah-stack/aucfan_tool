# AucFan リサーチツール — 移植・セットアップ手順

別のMacへ移植する際の完全手順書です。  
コンピュータ名・ユーザー名が変わる場合も考慮しています。

---

## 前提条件

| 項目 | 内容 |
|------|------|
| OS | macOS |
| Python | 3.11 以上（推奨 3.12〜3.14） |
| ブラウザ | Google Chrome（通常版） |
| ストレージ | Google Drive for Desktop（ストリーミングモード） |

### 2台構成について

このツールは2台のMacで役割を分担して運用することを想定しています。

| Mac | 役割 | SITE_ROLE |
|-----|------|-----------|
| 十王Mac | スクレイピング実行・画像/PDF を GDrive API でアップロード | `scraper` |
| 守谷Mac | GDriveミラーリングで結果を参照・閲覧専用 | `reader` |

---

## 1. リポジトリをクローン

```bash
cd ~/Downloads
git clone https://github.com/halhah-stack/aucfan_tool.git
cd aucfan_tool
```

---

## 2. Python 仮想環境を作成・依存パッケージをインストール

```bash
# 仮想環境を作成（既存の .venv は引き継がない — 別Macでは再作成すること）
python3 -m venv .venv

# 有効化
source .venv/bin/activate

# 依存パッケージをインストール
pip install -r requirements.txt
```

> **注意**: `.venv` フォルダはGitで管理されていません。  
> 別Macに .venv フォルダをコピーしても動きません。必ず `pip install` をやり直してください。

---

## 3. .env ファイルを設定する

`.env` ファイルを作成・編集します（既存ファイルをコピーして修正する場合も同様）。

```bash
cp .env.example .env
nano .env
```

### .env のテンプレート

```dotenv
# Gemini API キー（Google AI Studio で取得）
# https://aistudio.google.com/app/apikey
GEMINI_API_KEY=AIzaSy...（自分のAPIキーを入力）

# Chrome リモートデバッグ設定（通常は変更不要）
CHROME_DEBUG_HOST=127.0.0.1
CHROME_DEBUG_PORT=9222

# STEP1 スクレイピング設定
# MIN_DELAY / MAX_DELAY : ページ取得間の待機秒数
# MAX_PAGES             : 取得する最大ページ数
# ITEMS_PER_PAGE        : 1ページあたりの商品件数
MIN_DELAY=3.0
MAX_DELAY=5.0
MAX_PAGES=50
ITEMS_PER_PAGE=50

# STEP1 フィルタリング設定
# MIN_PRICE / MAX_PRICE : 一覧取得時の価格帯フィルター（円）
# MIN_GROUP_SIZE        : 仕入れ候補とする最小グループ件数（この件数以上 = 緑ラベル）
# PHASH_THRESHOLD       : 画像の類似度閾値（0=完全一致のみ / 大きいほど緩い判定）
MIN_PRICE=1000
MAX_PRICE=3000
MIN_GROUP_SIZE=5
PHASH_THRESHOLD=2

# Flask 設定（通常は変更不要）
FLASK_PORT=5001

# sellers_master.json の保存先（Google Drive）
SELLERS_MASTER_PATH=/Users/【ユーザー名】/Library/CloudStorage/GoogleDrive-【Gmailアドレス】/マイドライブ/AucFanToolData/sellers_master.json

# Gemini モデル設定
GEMINI_MODEL_TEXT=gemini-2.5-flash
GEMINI_MODEL_VISION=gemini-2.5-flash

# Gemini 有効/無効（false にすると pHash のみで動作）
GEMINI_ENABLED=true

# ──────────────────────────────────────────────
# Mac間の違いはここだけ（2行）
# ──────────────────────────────────────────────
# GDrive アップロード有効/無効（false にすると credentials.json 不要）
GDRIVE_UPLOAD_ENABLED=true

# サイトロール（scraper=十王Mac／reader=守谷Mac）
SITE_ROLE=scraper
```

---

## 4. Google Drive API 認証（scraper Mac のみ・十王Mac）

> `SITE_ROLE=reader`（守谷Mac）はこの手順不要です。

画像・PDFをGoogle Drive APIで直接アップロードするため、初回のみOAuth認証が必要です。

### 4-1. credentials.json を配置

`credentials.json`（Google Cloud ConsoleのOAuth2認証情報）を `aucfan_tool/` フォルダに配置してください。  
このファイルはGit管理外（`.gitignore`）のため、AirDropまたはGoogle Drive経由で転送してください。

### 4-2. 初回認証を実行

```bash
cd ~/Downloads/aucfan_tool
.venv/bin/python setup_gdrive_auth.py
```

ブラウザが開くのでGoogleアカウントにログインして許可してください。  
完了すると `token.json` が生成されます。

**確認メッセージ：**
```
✅ Google Drive に接続できました。アカウント: shinozakistore@gmail.com
```

> `token.json` はGit管理外です。機器ごとに生成されます。

---

## 5. Google Drive for Desktop の設定

1. [Google Drive for Desktop](https://www.google.com/drive/download/) をインストール
2. `shinozakistore@gmail.com` でサインイン
3. **十王Mac**：「ストリーミング」モードに設定（PDFやHTMLのミラーリング用途のみ）
4. **守谷Mac**：「ミラーリング」モードに設定（スクレイピング結果を自動同期して参照）

---

## 6. 動作確認

```bash
cd ~/Downloads/aucfan_tool
bash start.sh
```

`start.sh` は以下を自動で行います：

1. Chrome を通常終了
2. Flask（Python app.py）をバックグラウンドで起動
3. Chrome をリモートデバッグポート（9222）付きで再起動
4. ブラウザで `http://localhost:5001` を自動オープン

---

## 7. AucFan にログイン

`start.sh` 起動後、Chrome で以下の操作をしてください：

1. `aucfan.com` にアクセスしてログイン
2. 検索条件を設定して **1ページ目** を表示した状態にする
3. `http://localhost:5001` のタブに戻ってスクレイピング開始

---

## Tailscale 経由で別Macから閲覧する場合

スクレイピングをするMac（このツールが動いているMac）に Tailscale をインストールしてMeshVPNに接続すれば、別MacからもFlaskアプリにアクセスできます。

```
http://【TailscaleのMac IP】:5001
```

別Macでは **このツールのインストール・起動は不要** です。

---

## トラブルシューティング

### Chrome が起動しない / デバッグポートが開かない

```bash
# Chromeが残プロセスで残っていないか確認
ps aux | grep -i chrome

# 強制終了
killall "Google Chrome" 2>/dev/null
```

### Flask が起動しない（ModuleNotFoundError）

```bash
# 仮想環境が有効か確認
which python3
# → .venv/bin/python3 と表示されればOK

# 有効でない場合
source .venv/bin/activate
pip install -r requirements.txt
```

### GDrive認証エラー（credentials.json が見つかりません）

`credentials.json` が `aucfan_tool/` フォルダに存在するか確認してください。  
存在する場合は `setup_gdrive_auth.py` を再実行してください。

### `.env` の変更が反映されない

`.env` を編集したあとは **Flask を再起動**（`start.sh` を再実行）してください。

---

## ファイル構成（参考）

```
aucfan_tool/
├── app.py               # Flask メインアプリ
├── config.py            # 設定値（.env から読み込み）
├── scraper.py           # AucFan スクレイパー（STEP 1）
├── seller_analyzer.py   # セラー分析（STEP 2/3）
├── sellers_master.py    # マスターセラーリスト管理
├── data_manager.py      # データ保存・ロード
├── image_processor.py   # 画像ダウンロード・pHash計算・GDrive一括アップロード
├── gemini_client.py     # Gemini API クライアント
├── pdf_exporter.py      # PDF自動生成（STEP1/2/3完了時）
├── gdrive_uploader.py   # Google Drive API アップロードモジュール
├── setup_gdrive_auth.py # GDrive初回OAuth認証スクリプト（scraper Macのみ実行）
├── requirements.txt     # Python 依存パッケージ
├── start.sh             # 一発起動スクリプト
├── .env                 # 環境設定（★Gitで管理されない・各Macで作成）
├── .env.example         # .envのテンプレート
├── credentials.json     # GDrive OAuth認証情報（★Gitで管理されない・手動配置）
├── token.json           # GDrive認証トークン（★Gitで管理されない・自動生成）
├── .venv/               # 仮想環境（★Gitで管理されない・各Macで再作成）
├── templates/           # HTMLテンプレート
└── static/              # CSS/JS
```

> `.env`・`credentials.json`・`token.json`・`.venv` は `.gitignore` に含まれており、Gitで管理されません。  
> 別Macへ移植するときは必ず手動で用意してください。
