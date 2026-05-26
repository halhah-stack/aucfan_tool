# 引き継ぎメモ

> 最終更新：2026-05-27  
> 次のClaudeセッションはここから読んで作業を再開すること。

---

## 現在の実装状況

### ✅ 動作しているもの

| 機能 | ファイル | 状態 |
|---|---|---|
| AucFanスクレイピング | `scraper.py` | 完成・本番稼働中 |
| Amazon商品ページ取得（現在タブ） | `amazon_scraper.py` `fetch_amazon_product()` | 完成 |
| Amazon商品ページ取得（URL指定・短縮URL対応） | `amazon_scraper.py` `fetch_amazon_from_url()` | 完成 |
| 商品情報テーブル取得（折りたたみ展開） | `amazon_scraper.py` `_expand_and_parse()` | 完成 |
| 全商品画像URL取得 | `amazon_scraper.py` `image_urls` | 完成 |
| 評価（星数）抽出 | `amazon_scraper.py` | 完成（「5つ星のうち4.1」→4.1を正しく取得） |
| Excel 5シート生成 | `excel_exporter.py` | 完成 |
| Excel保存先フォルダ自動作成 | `app.py` `/api/export/excel/<group_id>` | 完成 |
| ExcelへのAmazonデータ追記 | `excel_append.py` `append_amazon()` | 完成 |
| Amazon全画像ダウンロード | `excel_append.py` `download_all_images()` | 完成 |
| /researchページ（Excelファイル一覧・選択） | `app.py` `_RESEARCH_HTML` | 完成 |
| /researchページ（Amazon URL追記） | `app.py` `/api/research/amazon/fetch-url-append` | 完成 |
| /researchページ（Excelダウンロード） | `app.py` `/api/research/excel/download` | 完成 |
| FBA料金シミュレータ自動入力 | `app.py` `/api/research/amazon/open-calculator` | 完成（Shadow DOM対応済） |
| Amazon取得中の進捗表示 | `app.py` `_research_fetch_status` + `/api/research/amazon/status` | 完成 |
| メインアプリからリサーチツールを開くボタン | `templates/index.html` | 完成 |

### ❌ 未実装のもの

| 機能 | 備考 |
|---|---|
| 1688スクレイパー | `app.py` `/research` の③1688欄は現在グレーアウト（準備中） |
| data_manager.py 複数ショップ対応 | 1688データ保存用 |
| app.py 1688エンドポイント | |
| UI「1688調査」タブ（メインアプリ） | |
| Claude Excel アドイン連携 | 後回し |

---

## ワークフロー（確定）

```
① AucFanで商品リサーチ → 商品カード表示
② 「📗 Excel」ボタン → 商品名フォルダ＋Excelを自動作成
③ 「📊 リサーチ追記ツールを開く」ボタン → localhost:5001/research を別ウィンドウで開く
   → Excelファイルをクリックして選択
   → ChromeでAmazonライバルページを開く
   → URLを貼り付けて「取得→追記」（複数ライバルを1件ずつ）
   → 「💴 FBA料金シミュレータで開く」ボタンでASINを自動入力
④ （未実装）1688調査 → Sheet4/5に追記
```

---

## フォルダ構成（保存先）

Excelボタン押下で以下のフォルダ構成が自動作成される：

```
~/マイドライブ/AucFanToolData/リサーチ結果/
  商品名/
    商品名_リサーチ.xlsx          ← 5シート構成Excel
    amazon/                        ← Amazonライバル画像
      B0XXXXX/
        01.jpg, 02.jpg, 03.jpg...  ← 全商品画像（カタログ参考用）
    1688/                          ← 1688仕入れ画像（未実装、フォルダのみ作成）
```

旧形式（フラットに保存されたExcel）も `/research` のファイル一覧で引き続き表示される。

---

## Excelの5シート構成（確定仕様）

### Sheet1 "①概要" — 意思決定ダッシュボード

```
[AucFan参考] 落札価格・商品名（1行のみ）
[Amazon競合サマリー] 最安値・最高値（Sheet2から自動参照）
[入力] 販売予定価格: [    ]  FBA手数料: [    ]  ← 手入力2セルのみ
[集計] ◎候補数・最高利益率（Sheet4から自動参照）
[判定] GO / 要検討
```

### Sheet2 "②Amazonライバル" — ライバル一覧（1ライバル1行）

```
列: ASIN | タイトル | 価格 | 評価 | レビュー数 | A+ | URL（実） | 入力URL | 画像
```
- 4行目以降に追記される
- 画像はExcelに埋め込み（列I）＋ amazon/{ASIN}/ フォルダにも全枚数保存

### Sheet3 "③Amazonテキスト" — スペック文オマージュ用

```
ASINごとにセパレーター行 ＋ 6行:
  タイトル / 価格 / 商品の特徴（箇条書き）/ 商品説明 / 仕様・詳細
```
- 「商品情報」「機能と仕様」テーブルの内容は「仕様・詳細」行に入る

### Sheet4 "④1688仕入れ" — 利益計算メイン（未追記）

```
列: ショップ名 | ショップURL | 信頼度 | 商品名（親） | バリアント名 |
    単価（元） | MOQ | 単価×MOQ | 原価（円）=単価×35 |
    利益=販売価格-原価-FBA | 利益率 | 判定◎×
```

### Sheet5 "⑤1688テキスト" — 仕入れ詳細（未追記）

---

## 原価計算の係数

```
単価（元） × 35 = 原価（円）
※ 35 = 送料・関税・代行手数料等を含む独自係数
```

## 仕入れ判断基準

```
利益率 ≥ 25% かつ 利益 ≥ 450円 → ◎（仕入れGO）
それ以外 → ×
```

---

## 主要ファイルまとめ

```
aucfan_tool/
├── app.py                    Flaskアプリ（ポート5001）・全APIエンドポイント
│                             /research ページのHTMLもインライン文字列で含む
├── config.py                 設定（CHROME_DEBUG_PORT, OUTPUT_BASE_DIR等）
├── data_manager.py           データ管理（items.json / amazon_data.json）
├── scraper.py                AucFanスクレイパー
├── amazon_scraper.py         Amazon商品ページスクレイパー
│   ├── _connect_chrome()     ポート9222の既存Chromeに接続
│   ├── _extract_asin(url)    URLからASIN抽出
│   ├── _extract_price(soup)  価格抽出
│   ├── _expand_and_parse()   折りたたみ展開→スクレイプ（全画像URL含む）
│   ├── fetch_amazon_product()  現在タブから取得
│   ├── fetch_amazon_from_url() URL指定取得（短縮URL対応）
│   └── resolve_short_url()   amzn.asia等の短縮URL解決
├── excel_exporter.py         Excel 5シート生成（AucFanデータ→Sheet1）
├── excel_append.py           Excel追記モジュール
│   ├── download_image()      メイン画像1枚ダウンロード
│   ├── download_all_images() 全画像を {ASIN}/ フォルダに保存
│   ├── ensure_product_folders() amazon/ 1688/ フォルダ確認・作成
│   ├── get_excel_info()      Excelの現在状態を返す
│   └── append_amazon()       Sheet2/3にAmazonデータ追記
├── static/app.js             フロントエンドJS（メインアプリUI）
├── templates/index.html      メインHTML（Amazon調査タブにリサーチツールボタンあり）
└── docs/
    ├── HANDOVER.md           ← このファイル
    ├── CODE_GUIDE.md
    ├── USER_GUIDE.md
    ├── SETUP.md
    └── QUICKSTART.md
```

---

## APIエンドポイント一覧

### メインアプリ

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/api/export/excel/<group_id>` | POST | Excel生成・商品名フォルダに保存 |
| `/api/amazon/fetch` | POST | 現在ChromeタブのAmazon情報取得 |

### /researchページ

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/research` | GET | リサーチ追記ツールページ |
| `/api/research/excel/list` | POST | Excelファイル一覧（サブフォルダ対応） |
| `/api/research/excel/load` | POST | Excel情報取得（シート名・件数等） |
| `/api/research/excel/download` | GET | Excelダウンロード（`?path=...`） |
| `/api/research/amazon/append` | POST | 現在タブ取得→Excel追記 |
| `/api/research/amazon/fetch-url-append` | POST | URL指定取得→Excel追記 |
| `/api/research/amazon/status` | GET | Amazon取得中ステータスのポーリング用 |
| `/api/research/amazon/open-calculator` | POST | FBA料金シミュレータにASIN自動入力 |

---

## 起動方法

```bash
cd ~/Downloads/aucfan_tool
./start.sh          # Chrome（ポート9222）＋ Flaskアプリ（ポート5001）を起動
```

ブラウザで `http://localhost:5001` を開く。  
リサーチ追記ツールは `http://localhost:5001/research`（または Amazon調査タブのボタンから）。

---

## FBA料金シミュレータ連携

URL: `https://sellercentral.amazon.co.jp/revcal?ref=RC2nonlogin`

- SellerCentralへのログインが必要（2段階認証あり）
- **手動でログイン後**、`/research` ページの「💴 FBA料金シミュレータで開く」ボタンが使える
- Seleniumが既存のログイン済みChromeセッションを使うため、再ログイン不要
- 既存の `revcal` タブがあれば再利用、なければ新規タブで開く

**Shadow DOM 対応（2026-05-27）**：
revcal ページは KAT UI フレームワーク製で `<kat-input>` 等のカスタム要素が Shadow DOM 内に `<input>` を持つ。
通常の CSS セレクターでは見つからないため、JS で Shadow Root を再帰的に辿って検索する実装にしている。
入力欄・送信ボタンの両方に同様の対応をしている（`api_open_fba_calculator()` 内）。

---

## Amazon取得中の進捗表示

`app.py` にグローバル変数 `_research_fetch_status` を追加。
`fetch-url-append` エンドポイントが処理の各ステップで更新し、フロントが1秒ごとにポーリングして表示する。

```
① URLを解析中...
② ChromeでAmazonページを開いています...（← 実際にSeleniumが動いている）
③ Excelに書き込み中...
  経過 X 秒 ／ Amazonページを閉じないでください
```

処理中はボタンが無効化されるため2重送信も防止できる。

---

## 次回セッションの作業順序

```
1. 1688スクレイパー実装
   ├── 1688_scraper.py 新規作成（amazon_scraper.py と同方式）
   ├── 取得項目: ショップ名/URL/信頼度/商品名/バリアント（名称・単価・MOQ）
   └── app.py に /api/research/1688/fetch-url-append エンドポイント追加

2. excel_append.py に append_1688() 関数追加
   ├── Sheet4（④1688仕入れ）に追記
   └── 1688/ フォルダに商品画像保存

3. /research ページの③1688欄を有効化

4. Claude Excel アドイン連携（ユーザー要望・詳細未定）
```

---

## GDriveアップロード（`gdrive_uploader.py`）

`gdrive_uploader.py` はメインアプリ（Flask / `app.py`）からは**直接呼ばれない**。
`image_processor.py` の2メソッドから自動呼び出しされる：

| 呼び出し元 | タイミング |
|---|---|
| `_copy_to_gdrive()` | 画像1枚ダウンロード直後 |
| `upload_images_to_gdrive()` | スクレイピング完了時（`scraper.py` の `run()` 終了後） |

条件：`GDRIVE_UPLOAD_ENABLED=true` かつ `SITE_ROLE=scraper` の場合のみ動作。
アップロード先：`GDrive: AucFanToolData/リサーチ結果/{セッション名}/images/`（S1/S2/S3すべて対象）。

**十王Mac 初回セットアップ（GDriveアップロードを使う場合）：**
```bash
cd ~/Downloads/aucfan_tool
source .venv/bin/activate
python setup_gdrive_auth.py
```
ブラウザでGoogleログイン → 許可 → `token.json` が生成されれば完了。以降は自動更新。

---

## 注意事項

- Chromeは必ず `start.sh` 経由で起動すること（ポート9222のデバッグオプションが必要）
- `driver.quit()` は呼ばない（Chromeを閉じてしまうため）。`fetch_amazon_from_url()` は新規タブを閉じるだけ
- Excel保存先: `config.OUTPUT_BASE_DIR` = `~/マイドライブ/AucFanToolData/リサーチ結果/`
- 旧形式（フラット保存）のExcelも `/research` のファイル一覧で表示・選択可能
