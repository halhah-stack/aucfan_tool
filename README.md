# AucFan リサーチツール

オークファンの落札データをスクレイピングして仕入れ候補を分析するツールです。

## 必要な環境

- macOS
- Python 3.11 以上
- Google Chrome（最新版）
- Gemini API キー（無料枠で動作）

## セットアップ手順（新しいMacの場合）

### 1. Python のインストール確認

```bash
python3 --version
```

Python 3.11 未満の場合は [python.org](https://www.python.org/) からインストール。

### 2. リポジトリをクローン

```bash
cd ~/Downloads
git clone https://github.com/halhah-stack/aucfan_tool.git
cd aucfan_tool
```

### 3. 仮想環境を作成してライブラリをインストール

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. 環境変数を設定

```bash
cp .env.example .env
```

`.env` をテキストエディタで開いて `GEMINI_API_KEY` を設定：

```
GEMINI_API_KEY=your_api_key_here
```

Gemini API キーは [Google AI Studio](https://aistudio.google.com/) で無料取得できます。

### 5. 起動

```bash
bash start.sh
```

1. Chrome（専用プロファイル）が起動する
2. ⌘T で新規タブを開き、AucFan にログイン
3. 検索条件を設定して1ページ目を表示
4. アプリ画面（`http://localhost:5001`）でキーワードを入力して「スクレイピング開始」

> **iPhone / iPad からも操作できます**  
> Mac と同じWi-Fiで `http://[MacのIP]:5001` にアクセス

## ライブラリ一覧

| ライブラリ | 用途 |
|-----------|------|
| selenium | Chrome 自動操作（スクレイピング） |
| beautifulsoup4 / lxml | HTML パース |
| imagehash / Pillow | 画像の pHash 計算・グループ化 |
| flask | ローカル Web アプリ |
| pandas / openpyxl | CSV・Excel 出力 |
| python-dotenv | .env 環境変数読み込み |
| google-generativeai | Gemini API（商品分類） |
| requests | 画像ダウンロード |
| pyyaml | プロンプト設定ファイル読み込み |

## 設定変更（.env で調整）

| 設定項目 | デフォルト | 説明 |
|---------|----------|------|
| FLASK_PORT | 5001 | Webアプリのポート番号 |
| MIN_PRICE | 1000円 | 取得する最低価格 |
| MAX_PRICE | 3000円 | 取得する最高価格 |
| MAX_PAGES | 500 | 最大スクレイピングページ数 |
| MIN_GROUP_SIZE | 5 | 仕入れ候補とする最小グループ件数 |
| MIN_DELAY / MAX_DELAY | 3〜5秒 | リクエスト間隔 |

## トラブルシューティング

**Port already in use エラー（macOS）**  
macOSのAirPlay受信機がポート5000を使用している場合があります。`.env` で `FLASK_PORT=5001` に変更してください。

**Chrome に接続できないエラー**  
`bash start.sh` で再起動してください。Chromeが専用プロファイルでデバッグモード起動します。

## 注意事項

- `.env` ファイルは GitHub にアップロードされません（APIキー保護のため）
- `リサーチ結果/` フォルダも GitHub にアップロードされません（大容量のため）
- スクレイピングはAucFanの利用規約の範囲内でご使用ください
