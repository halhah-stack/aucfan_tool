# AucFan リサーチツール

オークファンの落札データをスクレイピングして仕入れ候補を分析するツールです。

## 必要な環境

- macOS
- Python 3.11 以上
- Google Chrome
- ChromeDriver（Chromeと同じバージョン）
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
git clone https://github.com/YOUR_USERNAME/aucfan_tool.git
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

### 5. ChromeDriver のインストール確認

```bash
chromedriver --version
```

インストールされていない場合：

```bash
brew install chromedriver
```

Homebrew 未インストールの場合：

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

## 使い方

```bash
bash start.sh
```

1. Chrome が起動し、アプリ（localhost:5000）が開く
2. ⌘T で新規タブを開き、AucFan で検索条件を設定して1ページ目を表示
3. localhost:5000 のタブに戻り、キーワードを入力して「スクレイピング開始」

## インストール済みライブラリ一覧

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

## 設定変更

`config.py` で以下を調整できます：

| 設定項目 | デフォルト | 説明 |
|---------|----------|------|
| MIN_PRICE | 1000円 | 取得する最低価格 |
| MAX_PRICE | 3000円 | 取得する最高価格 |
| MAX_PAGES | 500 | 最大スクレイピングページ数 |
| MIN_GROUP_SIZE | 5 | 仕入れ候補とする最小グループ件数 |
| MIN_DELAY / MAX_DELAY | 3〜5秒 | リクエスト間隔 |

## 注意事項

- `.env` ファイルは GitHub にアップロードされません（APIキー保護のため）
- `リサーチ結果/` フォルダも GitHub にアップロードされません（大容量のため）
- スクレイピングはAucFanの利用規約の範囲内でご使用ください
