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
# リポジトリ直下に .env を作成
nano .env
```

### .env のテンプレート

```dotenv
# ──────────────────────────────────────────────
# Gemini API キー（Google AI Studio で取得）
# https://aistudio.google.com/app/apikey
# ──────────────────────────────────────────────
GEMINI_API_KEY=AIzaSy...（自分のAPIキーを入力）

# ──────────────────────────────────────────────
# Chrome リモートデバッグ設定（通常は変更不要）
# ──────────────────────────────────────────────
CHROME_DEBUG_HOST=127.0.0.1
CHROME_DEBUG_PORT=9222

# ──────────────────────────────────────────────
# スクレイピング設定
# ──────────────────────────────────────────────
MIN_DELAY=3.0
MAX_DELAY=5.0
MAX_PAGES=50
ITEMS_PER_PAGE=50

# ──────────────────────────────────────────────
# フィルタリング設定
# ──────────────────────────────────────────────
MIN_PRICE=1000
MAX_PRICE=3000
MIN_GROUP_SIZE=5
PHASH_THRESHOLD=2

# ──────────────────────────────────────────────
# Flask 設定
# ──────────────────────────────────────────────
FLASK_PORT=5001

# ──────────────────────────────────────────────
# 出力先・データ保存先（★ここをMacごとに書き換える）
# ──────────────────────────────────────────────
OUTPUT_BASE_DIR=/Users/【ユーザー名】/Library/CloudStorage/GoogleDrive-【Gmailアドレス】/マイドライブ/AucFanToolData
SELLERS_MASTER_PATH=/Users/【ユーザー名】/Library/CloudStorage/GoogleDrive-【Gmailアドレス】/マイドライブ/AucFanToolData/sellers_master.json

# ──────────────────────────────────────────────
# Gemini モデル設定
# ──────────────────────────────────────────────
GEMINI_MODEL_TEXT=gemini-2.5-flash
GEMINI_MODEL_VISION=gemini-2.5-flash
GEMINI_ENABLED=true
```

### ★ パスの確認方法（ユーザー名・Gmailアドレスを確認）

```bash
# ユーザー名を確認
whoami

# Google Drive のパスを確認（フォルダが存在するか確認）
ls ~/Library/CloudStorage/
# → "GoogleDrive-xxxx@gmail.com" という名前のフォルダが表示される

# 正しいパスをフルパスで確認
ls ~/Library/CloudStorage/GoogleDrive-【Gmailアドレス】/マイドライブ/
# → AucFanToolData フォルダが表示されればOK
```

**記入例（ユーザー名が `yamada`、Gmail が `yamada@gmail.com` の場合）:**

```dotenv
OUTPUT_BASE_DIR=/Users/yamada/Library/CloudStorage/GoogleDrive-yamada@gmail.com/マイドライブ/AucFanToolData
SELLERS_MASTER_PATH=/Users/yamada/Library/CloudStorage/GoogleDrive-yamada@gmail.com/マイドライブ/AucFanToolData/sellers_master.json
```

> **Google Drive が未インストールの場合:** パスをローカルフォルダに変更できます。
> ```dotenv
> OUTPUT_BASE_DIR=/Users/【ユーザー名】/Documents/AucFanToolData
> SELLERS_MASTER_PATH=/Users/【ユーザー名】/Documents/AucFanToolData/sellers_master.json
> ```

---

## 4. Google Drive for Desktop の設定

1. [Google Drive for Desktop](https://www.google.com/drive/download/) をインストール
2. `shinozakistore@gmail.com` でサインイン
3. 設定 → 「ストリーミング」モードに設定（ミラーリング不要）
4. `AucFanToolData` フォルダが `~/Library/CloudStorage/GoogleDrive-.../マイドライブ/` に表示されることを確認

---

## 5. 動作確認

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

## 6. AucFan にログイン

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

### Google Drive パスが見つからない（FileNotFoundError）

```bash
# パスを再確認
ls ~/Library/CloudStorage/
```

`.env` の `OUTPUT_BASE_DIR` が実際のパスと一致しているか確認してください。  
パス中の **Gmailアドレス** と **ユーザー名** を正確に記入することが重要です。

### `.env` の変更が反映されない

`.env` を編集したあとは **Flask を再起動**（`start.sh` を再実行）してください。

---

## ファイル構成（参考）

```
aucfan_tool/
├── app.py               # Flask メインアプリ
├── config.py            # 設定値（.env から読み込み）
├── scraper.py           # AucFan スクレイパー
├── seller_analyzer.py   # セラー分析
├── sellers_master.py    # マスターセラーリスト管理
├── data_manager.py      # データ保存・ロード
├── image_processor.py   # pHash 計算
├── gemini_client.py     # Gemini API クライアント
├── requirements.txt     # Python 依存パッケージ
├── start.sh             # 一発起動スクリプト
├── .env                 # 環境設定（★Gitで管理されない・各Macで作成）
├── .venv/               # 仮想環境（★Gitで管理されない・各Macで再作成）
├── templates/           # HTMLテンプレート
└── static/              # CSS/JS
```

> `.env` と `.venv` は `.gitignore` に含まれており、Gitで管理されません。  
> 別Macへ移植するときは必ず手動で作成してください。
