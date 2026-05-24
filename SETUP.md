# AucFan リサーチツール — セットアップ手順

別のMacへ移植する際の完全手順書です。  
ユーザー名・コンピュータ名が変わる場合も考慮しています。

---

## 運用モードを選ぶ

セットアップ前に、このMacをどのモードで使うか決めてください。

| モード | 用途 | `SITE_ROLE` | `GDRIVE_UPLOAD_ENABLED` | GDriveアプリ | `credentials.json` |
|---|---|---|---|---|---|
| ① scraper（十王Mac） | スクレイピング実行・GDriveへアップロード | `scraper` | `true` | ストリーミング | 必要 |
| ② reader（守谷Mac） | GDriveミラーリングで閲覧のみ | `reader` | `false` | ミラーリング | 不要 |
| ③ standalone（1台完結） | Google Driveなしで1台完結 | `scraper` | `false` | 不要 | 不要 |

---

## 前提条件

| 項目 | 内容 |
|------|------|
| OS | macOS |
| Python | 3.11 以上（推奨 3.12〜3.14） |
| ブラウザ | Google Chrome（通常版） |
| GDrive | モード①②のみ必要。③は不要 |

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
# 仮想環境を作成（既存の .venv は引き継がない — 別Macでは必ず再作成）
python3 -m venv .venv

# 有効化
source .venv/bin/activate

# 依存パッケージをインストール
pip install -r requirements.txt
```

> **注意**: `.venv` フォルダはGitで管理されていません。  
> 別Macに `.venv` フォルダをコピーしても動きません。必ず `pip install` をやり直してください。

---

## 3. .env ファイルを設定する

テンプレートをコピーして編集します。

```bash
cp .env.example .env
nano .env   # または好みのエディタで開く
```

### モード別 .env 設定例

**モード① 十王Mac（scraper）**

```dotenv
GEMINI_API_KEY=AIzaSy...（取得済みのキー）
SITE_ROLE=scraper
GDRIVE_UPLOAD_ENABLED=true
# 以下は config.py が自動検出するため設定不要
# （OUTPUT_BASE_DIR / SELLERS_MASTER_PATH / LOCAL_IMAGE_CACHE_DIR）
```

**モード② 守谷Mac（reader）**

```dotenv
GEMINI_API_KEY=AIzaSy...（取得済みのキー）
SITE_ROLE=reader
GDRIVE_UPLOAD_ENABLED=false
# 以下は config.py が自動検出するため設定不要
```

**モード③ スタンドアロン（1台完結・GDriveなし）**

```dotenv
GEMINI_API_KEY=AIzaSy...（取得済みのキー）
SITE_ROLE=scraper
GDRIVE_UPLOAD_ENABLED=false
OUTPUT_BASE_DIR=リサーチ結果
SELLERS_MASTER_PATH=data/sellers_master.json
```

### 共通オプション設定（任意）

```dotenv
# スクレイピング速度（短すぎるとBANリスク）
MIN_DELAY=3.0
MAX_DELAY=5.0
MAX_PAGES=50
ITEMS_PER_PAGE=50

# 価格フィルター（円）
MIN_PRICE=1000
MAX_PRICE=3000
MIN_GROUP_SIZE=5
PHASH_THRESHOLD=2

# Geminiモデル
GEMINI_MODEL_TEXT=gemini-3.5-flash
GEMINI_MODEL_VISION=gemini-3.5-flash
GEMINI_ENABLED=true

# Flask
FLASK_PORT=5001
```

> **パスの手動指定について**: `OUTPUT_BASE_DIR` などにパスを書く場合は、そのMacのユーザー名に合わせてください。別Macの `/Users/ユーザー名/...` をそのままコピーしても動きません（パスが存在しないためエラーになります）。`config.py` が自動検出するため、通常は書かなくてOKです。

---

## 4. credentials.json の配置（モード①のみ）

> モード②③ はこの手順不要です。

画像・PDFをGoogle Drive APIで直接アップロードするため、**OAuth認証用ファイル**が必要です。

### credentials.json とは

Google Cloud Consoleで発行する認証情報ファイルです。Google Cloud Consoleからダウンロードした際のファイル名は `client_secret_xxxxxxxxx.apps.googleusercontent.com.json` ですが、**`credentials.json` にリネームして `aucfan_tool/` フォルダに配置**してください。

```
aucfan_tool/
└── credentials.json   ← ここに配置（Git管理外・AirDropまたはGDrive経由で転送）
```

### 初回OAuth認証を実行

```bash
cd ~/Downloads/aucfan_tool
.venv/bin/python setup_gdrive_auth.py
```

ブラウザが開くので Googleアカウントにログインして「許可」をクリックしてください。  
完了すると `token.json` が自動生成されます。

```
✅ Google Drive に接続できました。アカウント: shinozakistore@gmail.com
```

> `token.json` はGit管理外です。機器ごとに生成されます。  
> `credentials.json` と `token.json` は他人に見せないでください（Googleアカウントへのアクセス権が含まれます）。

---

## 5. Google Drive for Desktop の設定（モード①②のみ）

> モード③ はこの手順不要です。

1. [Google Drive for Desktop](https://www.google.com/drive/download/) をインストール
2. `shinozakistore@gmail.com` でサインイン
3. モードに応じて同期方式を設定：

| モード | 設定 | 説明 |
|---|---|---|
| ① scraper（十王Mac） | **ストリーミング** | ファイルは必要なときだけダウンロード。GDrive API でアップロードするのでミラーリング不要 |
| ② reader（守谷Mac） | **ミラーリング** | 全ファイルをローカルに同期。`~/マイドライブ（メールアドレス）/` が作成され、画像がすぐ表示できる |

**ミラーリングの設定手順（守谷Mac）**：  
Google Driveアプリを開く → 環境設定 → 「マイドライブの同期オプション」→「このデバイスにファイルをミラーリング」を選択 → 保存

同期完了すると `~/マイドライブ（shinozakistore@gmail.com）/AucFanToolData/` が利用可能になります。

---

## 6. 動作確認・起動

```bash
cd ~/Downloads/aucfan_tool
bash start.sh
```

`start.sh` は以下を自動で行います：

1. Chrome を通常終了
2. Flask（`app.py`）をバックグラウンドで起動
3. Chrome をリモートデバッグポート（9222）付きで再起動
4. ブラウザで `http://localhost:5001` を自動オープン

---

## 7. AucFan にログイン（モード①③のみ）

`start.sh` 起動後、Chrome で以下の操作をしてください：

1. `aucfan.com` にアクセスしてログイン
2. 検索条件を設定して **1ページ目** を表示した状態にする
3. `http://localhost:5001` のタブに戻ってスクレイピング開始

---

## 除外ルールのメンテナンス

除外キーワードはすべて **`rules.yaml`** で一元管理しています。コードを触る必要はありません。

```bash
# rules.yaml を編集（テキストエディタで開く）
open ~/Downloads/aucfan_tool/rules.yaml   # macOS のデフォルトエディタで開く

# 変更を反映するには再起動
bash start.sh
```

**追記する場所の目安**：

| 追加したい内容 | 書く場所 |
|---|---|
| 商品名キーワード除外 | `title_keywords:` セクション |
| メーカー・ブランド名除外 | `maker_keywords:` セクション |
| Gemini分析で提案されたキーワード | `title_keywords:` と `custom_rules:` の両方 |

---

## 役割の切り替え方（scraper ↔ reader ↔ standalone）

`switch_role.sh` スクリプトでワンコマンド切り替えができます。`.env` の手作業編集は不要です。

```bash
bash ~/Downloads/aucfan_tool/switch_role.sh scraper     # スクレイピング専用に切り替え
bash ~/Downloads/aucfan_tool/switch_role.sh reader      # 閲覧専用に切り替え
bash ~/Downloads/aucfan_tool/switch_role.sh standalone  # 1台完結（GDrive不要）に切り替え
```

実行すると `.env` が自動更新され、残りの手動作業（GDriveアプリのモード変更など）が画面に表示されます。

### scraper → reader に変える場合（スクリプト実行後の手動作業）

1. Google Driveアプリを「ストリーミング」→「**ミラーリング**」に変更
   - Google Driveアプリ → 環境設定 → マイドライブの同期オプション → 「このデバイスにファイルをミラーリング」→ 保存
2. GDriveの同期完了を待つ
3. `bash start.sh` でアプリを再起動

### reader → scraper に変える場合（スクリプト実行後の手動作業）

1. Google Driveアプリを「ミラーリング」→「**ストリーミング**」に変更
2. `credentials.json` を配置（初回のみ）
3. `setup_gdrive_auth.py` で認証を実行（初回のみ）：
   ```bash
   cd ~/Downloads/aucfan_tool && .venv/bin/python setup_gdrive_auth.py
   ```
4. `bash start.sh` でアプリを再起動

### standalone に変える場合（スクリプト実行後の手動作業）

`bash start.sh` でアプリを再起動するだけでOKです。GDrive・credentials.json は不要です。

---

## Tailscale 経由で別Macから閲覧する場合

スクレイピングをするMacに Tailscale をインストールしてMeshVPNに接続すれば、別MacからもFlaskアプリにアクセスできます。

```
http://【TailscaleのMac IP】:5001
```

別Macでは**このツールのインストール・起動は不要**です。

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

`.env` を編集したあとは **アプリを再起動**（`Ctrl+C` で停止 → `bash start.sh`）してください。  
また、ターミナルで `echo $OUTPUT_BASE_DIR` などを実行して古い環境変数が残っていないか確認してください。残っている場合は `unset OUTPUT_BASE_DIR` を実行してから再起動してください。

### Google Drive のセッションが見つからない

ターミナルで以下を実行して `config.py` が参照しているパスを確認してください：

```bash
cd ~/Downloads/aucfan_tool
.venv/bin/python3 -c "import config; print('OUTPUT:', config.OUTPUT_BASE_DIR); print('IMAGE:', config.LOCAL_IMAGE_CACHE_DIR)"
```

表示されたパスが実際に存在するか Finder で確認してください。

---

## ファイル構成（参考）

```
aucfan_tool/
├── app.py               # Flask メインアプリ
├── config.py            # 設定値（.envから読み込み・GDriveパス自動検出）
├── scraper.py           # AucFan スクレイパー（STEP 1）
├── seller_analyzer.py   # セラー分析（STEP 2/3）
├── sellers_master.py    # マスターセラーリスト管理
├── data_manager.py      # データ保存・ロード
├── image_processor.py   # 画像ダウンロード・pHash計算・GDrive一括アップロード
├── gemini_client.py     # Gemini API クライアント
├── pdf_exporter.py      # PDF自動生成（STEP完了時）
├── excel_exporter.py    # Excel リサーチシート生成（商品カードの📗ボタンから呼び出し）
├── build_template.py    # リサーチ_テンプレート.xlsx を生成するスクリプト（初回・再生成時に実行）
├── リサーチ_テンプレート.xlsx  # Excelエクスポートのフォーマットテンプレート（Excelで自由に編集可）
├── gdrive_uploader.py   # Google Drive API アップロードモジュール
├── setup_gdrive_auth.py # GDrive初回OAuth認証スクリプト（モード①のみ実行）
├── requirements.txt     # Python 依存パッケージ
├── start.sh             # 一発起動スクリプト
├── switch_role.sh       # 役割切り替えスクリプト（scraper/reader/standalone）
├── .env                 # ★ 環境設定（Gitで管理されない・各Macで作成）
├── .env.example         # .env のテンプレート（3モードのコメント付き）
├── credentials.json     # ★ GDrive OAuth認証情報（Gitで管理されない・モード①のみ必要）
│                        #   Google Cloud Console からダウンロードした
│                        #   client_secret_xxx.json を credentials.json にリネームして配置
├── token.json           # ★ GDrive認証トークン（Gitで管理されない・自動生成）
├── .venv/               # ★ 仮想環境（Gitで管理されない・各Macで再作成）
├── templates/           # HTMLテンプレート
└── static/              # CSS/JS
```

> ★ のファイル・フォルダは `.gitignore` で管理対象外です。  
> 別Macへ移植するときは手動で用意してください。

---

*最終更新: 2026年5月24日（switch_role.sh による役割切り替えスクリプト追加）*
