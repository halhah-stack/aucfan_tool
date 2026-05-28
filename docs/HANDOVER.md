# 引き継ぎメモ

> 最終更新：2026-05-29（6回目）  
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
| Excel保存先フォルダ自動作成（リサーチシートフォルダ） | `app.py` `/api/export/excel/<group_id>` | 完成 |
| ExcelへのAmazonデータ追記 | `excel_append.py` `append_amazon()` | 完成 |
| Amazon全画像ダウンロード | `excel_append.py` `download_all_images()` | 完成 |
| /researchページ（Excelファイル一覧・選択） | `app.py` `_RESEARCH_HTML` | 完成 |
| /researchページ（Excelファイル削除ボタン） | `app.py` `/api/research/excel/delete` | 完成（2026-05-29追加） |
| /researchページ（Amazon URL追記） | `app.py` `/api/research/amazon/fetch-url-append` | 完成 |
| /researchページ（Excelダウンロード） | `app.py` `/api/research/excel/download` | 完成 |
| FBA料金シミュレータ自動入力（新タブで開く） | `app.py` `/api/research/amazon/open-calculator` | 完成（2026-05-29修正） |
| FBA利益計算結果をExcelに転記 | `app.py` `/api/research/amazon/read-calc` | 完成（2026-05-29追加） |
| Amazon取得中の進捗表示 | `app.py` `_research_fetch_status` + `/api/research/amazon/status` | 完成 |
| メインアプリからリサーチツールを開くボタン | `templates/index.html` | 完成 |
| 1688商品ページ取得（URL指定） | `scraper_1688.py` `fetch_1688_from_url()` | 完成 |
| Excelへの1688データ追記 | `excel_append.py` `append_1688()` | 完成（Sheet4/5 + 画像保存） |
| /researchページ（1688 URL追記） | `app.py` `/api/research/1688/fetch-url-append` | 完成 |
| 1688取得中の進捗表示 | `app.py` `_research_1688_fetch_status` + `/api/research/1688/status` | 完成 |

### ❌ 未実装のもの

| 機能 | 備考 |
|---|---|
| UI「1688調査」タブ（メインアプリ） | メインアプリ側への統合（後回し） |
| Claude Excel アドイン連携 | 後回し |

---

## ワークフロー（確定）

```
① AucFanで商品リサーチ → 商品カード表示
② 「📗 Excel」ボタン → 商品名フォルダ＋Excelを自動作成（リサーチシートフォルダに保存）
③ 「📊 リサーチ追記ツールを開く」ボタン → localhost:5001/research を別ウィンドウで開く
   → Excelファイルをクリックして選択
   → ChromeでAmazonライバルページを開く
   → URLを貼り付けて「取得→追記」（複数ライバルを1件ずつ）
   → 「💴 FBA料金シミュレータで開く」ボタン → 新タブでrevcalページを開きASINを自動入力
   → revcalで原価を手入力し利益計算後、「📥 計算結果をExcelに転記」ボタンで転記
④ 1688調査 → 1688商品ページのURLを貼り付けて「取得→追記」→ Sheet4/5に追記
```

---

## フォルダ構成（保存先）

**Excel（リサーチシート）とスクレイピングデータ（リサーチ結果）は別フォルダに分離している。**

```
~/マイドライブ（shinozakistore@gmail.com）/AucFanToolData/
  リサーチシート/               ← Excelファイル（EXCEL_BASE_DIR）
    商品名/
      商品名_リサーチ.xlsx      ← 5シート構成Excel
      amazon/                   ← Amazonライバル画像
        B0XXXXX/
          01.jpg, 02.jpg...
      1688/                     ← 1688仕入れ画像

  リサーチ結果/                 ← AucFanスクレイピングデータ（OUTPUT_BASE_DIR）
    セッション名/
      images/
```

- **誤削除防止のために分離した**: リサーチ結果（スクレイピングデータ）とExcelが同じフォルダにあると、UIからExcelを削除する際にスクレイピングデータを誤削除するリスクがあった
- UIのファイル一覧は `EXCEL_BASE_DIR`（リサーチシート）を優先して表示する
- 旧形式（フラット保存）のExcelも `/research` のファイル一覧で引き続き表示される

---

## Excelの5シート構成（確定仕様）

### Sheet1 "①概要" — 意思決定ダッシュボード

```
[AucFan参考] 落札価格・商品名（1行のみ）
[Amazon競合サマリー] 最安値・最高値（Sheet2から自動参照）
[入力] 販売予定価格: [    ]  FBA手数料: [    ]  ← 手入力2セルのみ（B12・B13）
[集計] ◎候補数・最高利益率（Sheet4から自動参照）
[判定] GO / 要検討
```

- B12 = 販売価格（手入力 or read-calcが自動入力）
- B13 = FBA手数料（read-calcが自動入力、空欄の場合のみ）

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

### Sheet4 "④1688仕入れ" — 利益計算メイン

```
列: ショップ名 | ショップURL | 信頼度 | 商品名（親） | バリアント名 |
    単価（元） | MOQ | 単価×MOQ | 原価（円）=単価×35 |
    利益=販売価格-原価-FBA | 利益率 | 判定◎×
```

- Q列・R列の数式参照は `'①概要'!B12`（販売価格）/ `'①概要'!B13`（FBA手数料）を使用
  - **注意**: `Sheet1!B12` ではなくシート名で参照すること（#REF!エラーになる）

### Sheet5 "⑤1688テキスト" — 仕入れ詳細

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
├── config.py                 設定（CHROME_DEBUG_PORT, OUTPUT_BASE_DIR, EXCEL_BASE_DIR等）
├── .env                      環境変数オーバーライド（守谷Mac専用パスを記載）
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
├── scraper_1688.py           1688商品ページスクレイパー（旧: 1688_scraper.py→リネーム）
│   ├── _connect_chrome()     ポート9222の既存Chromeに接続（同方式）
│   ├── _parse_price_from_text()  "预估到手单价" 優先で価格抽出
│   ├── _parse_moq_from_text()    "20套起批"→(20,"套") 抽出
│   ├── _parse_variants_from_body()  规格セクションのSKU一覧を抽出
│   ├── _parse_shop_info()    ショップ名/URL/評価/回頭率取得
│   └── fetch_1688_from_url() メイン関数（URLからフルデータ返却）
├── excel_exporter.py         Excel 5シート生成（AucFanデータ→Sheet1）
├── excel_append.py           Excel追記モジュール
│   ├── download_image()      メイン画像1枚ダウンロード
│   ├── download_all_images() 全画像を {ASIN}/ または {shop}/ フォルダに保存
│   ├── ensure_product_folders() amazon/ 1688/ フォルダ確認・作成
│   ├── get_excel_info()      Excelの現在状態を返す
│   ├── append_amazon()       Sheet2/3にAmazonデータ追記
│   └── append_1688()         Sheet4/5に1688データ追記（バリアント×行）
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
| `/api/export/excel/<group_id>` | POST | Excel生成・リサーチシートフォルダに保存 |
| `/api/amazon/fetch` | POST | 現在ChromeタブのAmazon情報取得 |

### /researchページ

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/research` | GET | リサーチ追記ツールページ |
| `/api/research/excel/list` | POST | Excelファイル一覧（サブフォルダ対応） |
| `/api/research/excel/load` | POST | Excel情報取得（シート名・件数等） |
| `/api/research/excel/download` | GET | Excelダウンロード（`?path=...`） |
| `/api/research/excel/delete` | POST | Excelファイル削除（`{path:...}`） |
| `/api/research/amazon/append` | POST | 現在タブ取得→Excel追記 |
| `/api/research/amazon/fetch-url-append` | POST | URL指定取得→Excel追記 |
| `/api/research/amazon/status` | GET | Amazon取得中ステータスのポーリング用 |
| `/api/research/amazon/open-calculator` | POST | FBA料金シミュレータを新タブで開きASIN自動入力 |
| `/api/research/amazon/read-calc` | POST | revcal利益計算結果をExcel Sheet1（B12/B13）に転記 |
| `/api/research/1688/fetch-url-append` | POST | 1688 URL指定取得→Excel追記（Sheet4/5） |
| `/api/research/1688/status` | GET | 1688取得中ステータスのポーリング用 |

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
（URLは変わる可能性あり。`.env` の `REVCAL_URL` で変更可能）

- SellerCentralへのログインが必要（2段階認証あり）
- **手動でログイン後**、`/research` ページの「💴 FBA料金シミュレータで開く」ボタンが使える
- Seleniumが既存のログイン済みChromeセッションを使うため、再ログイン不要

### 新タブでの開き方（2026-05-29修正）

`window.open()` はChrome拡張設定によりポップアップブロックされることがあるため、Seleniumの `switch_to.new_window("tab")` を使用している：

```python
driver.switch_to.new_window("tab")   # 確実に新タブ生成
driver.get(CALC_URL)                  # revcalへ移動
time.sleep(3)                         # ページ読み込み待ち
```

### ASIN自動入力（Shadow DOM対応）

revcal ページは KAT UI フレームワーク製で `<kat-input>` 等のカスタム要素が Shadow DOM 内に `<input>` を持つ。通常の CSS セレクターでは見つからないため、JS で Shadow Root を再帰的に辿って検索する。

さらに、KAT フレームワークは `send_keys()` や `nativeInput.set.call()` では値変化イベントを認識しないため、**1文字ずつ KeyboardEvent を dispatch** する方式を採用：

```python
driver.execute_script("""
    var el = arguments[0], val = arguments[1];
    el.scrollIntoView({block:'center'});
    el.click();
    el.focus();
    el.value = '';
    for (var i = 0; i < val.length; i++) {
        var ch = val[i];
        el.dispatchEvent(new KeyboardEvent('keydown',  {key:ch, bubbles:true}));
        el.dispatchEvent(new KeyboardEvent('keypress', {key:ch, bubbles:true}));
        el.value += ch;
        el.dispatchEvent(new Event('input', {bubbles:true}));
        el.dispatchEvent(new KeyboardEvent('keyup',    {key:ch, bubbles:true}));
    }
    el.dispatchEvent(new Event('change', {bubbles:true}));
""", input_el, asin)
```

### FBA結果の読み取り・Excel転記（2026-05-29追加）

`/api/research/amazon/read-calc` エンドポイント：

1. revcalページを `collectText()` でスクレイプ（Shadow DOM対応の再帰テキスト収集）
2. 販売価格・FBA手数料を正規表現で抽出
3. `'①概要'`シート B12（販売価格、空欄の場合のみ書き込み）・B13（FBA手数料、常に書き込み）を更新
4. Sheet4（`'④1688仕入れ'`）の利益率・利益を参照し、◎ GO 条件（利益率≥25% or 利益≥450円）を評価して返す

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

## 環境設定（config.py / .env）

### 主要設定値

| 変数 | デフォルト値 | 説明 |
|---|---|---|
| `OUTPUT_BASE_DIR` | GDrive: `マイドライブ/AucFanToolData/リサーチ結果` | スクレイピングデータ保存先 |
| `EXCEL_BASE_DIR` | GDrive: `マイドライブ/AucFanToolData/リサーチシート` | **Excel保存先（スクレイピングと分離）** |
| `CNY_TO_JPY_RATE` | `35` | 1688価格→円換算係数 |
| `REVCAL_URL` | `https://sellercentral.amazon.co.jp/revcal?ref=RC2nonlogin` | FBAシミュレータURL |
| `PROFIT_RATE_THRESHOLD` | `25` | 仕入れ判断: 利益率閾値（%） |
| `PROFIT_YEN_THRESHOLD` | `450` | 仕入れ判断: 利益額閾値（円） |
| `MIN_PRICE` | `1000` | スクレイピング対象: 最小価格 |
| `MAX_PRICE` | `3000` | スクレイピング対象: 最大価格 |
| `FLASK_PORT` | `5001` | Flaskポート番号 |

### GDrive パス自動検出ロジック（`config.py` `_find_gdrive_aucfan_root()`）

```python
def _find_gdrive_aucfan_root() -> str:
    home = Path.home()
    # 1. ミラーリングモード - AucFanToolData が存在すれば有効（サブフォルダの有無は問わない）
    for candidate in sorted(home.glob("マイドライブ*")):
        p = candidate / "AucFanToolData"
        if p.exists():
            return str(p)
    # 2. ストリーミングモード（CloudStorage経由）
    cloud = home / "Library" / "CloudStorage"
    if cloud.exists():
        for gd in sorted(cloud.glob("GoogleDrive-*")):
            p = gd / "マイドライブ" / "AucFanToolData"
            if p.exists():
                return str(p)
    return None
```

**注意（守谷Mac）**: ホームに `マイドライブ/`（メールなし）と `マイドライブ（shinozakistore@gmail.com）/`（メールあり）の2つが存在する。glob sort で前者が先に来て誤検出する場合があるため、`.env` に `EXCEL_BASE_DIR` を明示的に設定している。

### 守谷Mac の `.env` 設定（抜粋）

```dotenv
OUTPUT_BASE_DIR=/Users/shino/Library/CloudStorage/GoogleDrive-shinozakistore@gmail.com/マイドライブ/AucFanToolData/リサーチ結果
EXCEL_BASE_DIR=/Users/shino/マイドライブ（shinozakistore@gmail.com）/AucFanToolData/リサーチシート
LOCAL_IMAGE_CACHE_DIR=/Users/shino/Library/CloudStorage/GoogleDrive-shinozakistore@gmail.com/マイドライブ/AucFanToolData/リサーチ結果
SELLERS_MASTER_PATH=/Users/shino/Library/CloudStorage/GoogleDrive-shinozakistore@gmail.com/マイドライブ/AucFanToolData/sellers_master.json
```

---

## 次回セッションの作業候補

### ⚡ セッション開始直後にやること（必ずここから）

```bash
# 1. 最新コードを取得
cd ~/Downloads/aucfan_tool
git pull

# 2. アプリ起動
./start.sh
# → Chrome（ポート9222）とFlask（ポート5001）が起動する
# → ブラウザで http://localhost:5001 が開く
```

---

### ✅ チェック1: Excel作成・保存先確認（所要2分）

**操作手順:**
1. AucFanリサーチツール（localhost:5001）でAucFanの商品カードを表示
2. 商品カードの「📗 Excel」ボタンをクリック
3. 成功メッセージが出たら以下を確認

**確認コマンド:**
```bash
# Excelが正しい場所（リサーチシート）に保存されているか確認
find ~/マイドライブ\ \(shinozakistore@gmail.com\)/AucFanToolData/リサーチシート/ -name "*.xlsx" | head -5
```

**期待結果:** `~/マイドライブ（shinozakistore@gmail.com）/AucFanToolData/リサーチシート/商品名/商品名_リサーチ.xlsx` が存在する  
**NG例:** `~/マイドライブ/AucFanToolData/...`（メールなしフォルダ）に保存されていたら `.env` の `EXCEL_BASE_DIR` を確認

---

### ✅ チェック2: ファイル一覧・削除ボタン確認（所要2分）

**操作手順:**
1. ブラウザで `http://localhost:5001/research` を開く
2. Excelファイルが一覧に表示されるか確認
3. ファイルをクリックして選択できるか確認
4. 🗑ボタンが表示されるか確認（クリックはテスト用ファイルで）

**NG時の確認ポイント:**
- ファイルが表示されない → `EXCEL_BASE_DIR` のパスが存在するか確認
- 選択できない → ブラウザのコンソール（F12）でJSエラーを確認してClaudeに貼る

---

### ✅ チェック3: FBAシミュレータ新タブ確認（所要3分）

**前提:** SellerCentralに手動でログインしておく（2段階認証あり）

**操作手順:**
1. `/research` でExcelファイルを選択（ASINが入っているもの）
2. 「💴 FBAシミュレータで開く」ボタンをクリック
3. **新タブ**でrevcalページが開くか確認
4. ASINが入力欄に自動入力されているか確認

**NG例と対処:**
- 同じタブで開く → `app.py` の `api_open_fba_calculator()` の `switch_to.new_window` を確認
- ASINが入力されない → ブラウザのコンソールでエラー確認 or Seleniumログを確認してClaudeに貼る

---

### ✅ チェック4: FBA結果Excel転記確認（所要5分）

**前提:** チェック3でrevcalが開いてASINが入力済みの状態

**操作手順:**
1. revcalの原価欄に金額を手入力（例: 500）
2. 計算を実行してFBA手数料・販売価格が表示されるのを確認
3. `/research` ページに戻り「📥 計算結果をExcelに転記」ボタンをクリック
4. Excelを開いて `①概要` シートの B12・B13 を確認

**期待結果:**
- B12: 販売価格（円）
- B13: FBA手数料（円）
- Sheet4のQ列・R列に利益・利益率が計算されている

**NG時:** エラーメッセージをそのままClaudeに貼る

---

### 📋 未着手タスク

```
- Claude Excel アドイン連携（ユーザー要望・詳細未定）
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

## 1688スクレイパー（`scraper_1688.py`）

`amazon_scraper.py` と同じ Chrome port 9222 接続方式。

**取得できる主要データ：**
- 商品タイトル（`.offer-title` 全候補の最長テキストを採用 ← AliPrice等のプラグイン注入対策）
- タイトル日本語訳（`title_ja`）：`deep_translator.GoogleTranslator` で中国語→日本語に自動翻訳
- 価格：`od-price-container` から "预估到手单价" を優先取得
- MOQ："20套起批" 形式をパース → `(20, "套")`
- バリアント：body テキストのバリアントセクション（`ENTRY_HEADERS`/`STOP_HEADERS` 方式で分類）
  - `ENTRY_HEADERS = {'规格','尺寸','颜色','型号','款式','规格型号','包装规格'}` → バリアント行として取得
  - `STOP_HEADERS = {'套餐','数量','颜色分类'}` → これが来たらセクション終了（套餐を誤取込しない）
  - フォーマットA: 名称 / ¥価格 / 库存N（3行別々）
  - フォーマットB: 名称 / ¥価格库存N（価格と在庫が同一行）← 両対応
  - 各バリアント辞書に `name_ja`（日本語訳）も含む
- ショップURL：**サブドメイン方式**で検出（`_is_shop_subdomain_url()`）
  - JS で全 `<a>` タグを走査し `[shopname].1688.com` 形式の URL を抽出
  - `www/s/detail/login` 等の既知非ショップサブドメインは除外
  - ポジティブ検出方式のため `/page/offerlist.htm` を含むショップURLも正しく取得できる
- 画像：`img[src*='cbu01']`

**戻り値に追加されたフィールド：**
- `title_ja`（商品名日本語訳）
- `shop_years`（例: "9年"/"3ヶ月"）
- `variants[].name_ja`（バリアント名日本語訳）

**注意：**
- ファイル名が `1688_scraper.py` だと Python がインポートできないため `scraper_1688.py` にリネーム済み
- バリアントなし商品は `variants=[{"name":"デフォルト","price":X,"stock":Y,"name_ja":""}]` として返す
- `deep_translator` は通信失敗時でも空文字で握りつぶす（翻訳失敗でスクレイピング全体が止まらない）

---

## Sheet4 列構成（19列・確定仕様）

| 列 | 内容 | 種別 |
|---|---|---|
| A | 仕入れ選択（◎/○/×） | 手入力（薄黄背景） |
| B | ショップ名 | 自動 |
| C | ショップURL | 自動（ハイパーリンク） |
| D | 信頼度（評価/回頭率） | 自動 |
| E | 入驻年数 | 自動 |
| F | 商品名（中国語） | 自動 |
| G | 商品名（日本語） | **自動翻訳**（deep_translator） |
| H | バリアント（中国語） | 自動 |
| I | バリアント（日本語） | **自動翻訳**（deep_translator） |
| J | 在庫数 | 自動 |
| K | 単価(CNY) | 自動 |
| L | **係数(×JPY)** = CNY_TO_JPY_RATE | **自動（新規追加）** |
| M | MOQ | 自動（未指定時=1） |
| N | 仕入総額(CNY) = K×M | 数式 |
| O | 仕入総額(JPY) = K×M×L | 数式 |
| P | 原価/個(JPY) = K×L | 数式 |
| Q | 利益(JPY) = 販売価格-FBA-P | 数式（`='①概要'!B12-'①概要'!B13-P{r}`） |
| R | 利益率 | 数式（`=TEXT(Q{r}/'①概要'!B12,"0.0%")`） |
| S | 判定（◎ GO / × 再検討） | 数式 |

- 係数（デフォルト35）は `.env` の `CNY_TO_JPY_RATE=35` で変更可能
- 販売価格 = `'①概要'!B12`、FBA手数料 = `'①概要'!B13`
- **`Sheet1!B12` ではなく `'①概要'!B12` で参照すること**（シート名が日本語のため）
- G列・I列は `deep_translator.GoogleTranslator` で自動翻訳して書き込む
- **既存Excelは列が古い形式のため、新規作成すると新19列レイアウトが適用される**

---

## Amazon タブ管理（CDP方式）

AucFanツール本体からAmazon検索ページを開いたまま、リサーチ追記ツールでURLを取得すると「既存のAmazonタブが残っている」という問題が発生する。これを自動解決するため **CDP（Chrome DevTools Protocol）** 方式を採用。

```python
# amazon_scraper.py — fetch_amazon_from_url() 内でスクレイピング後に実行
result = driver.execute_cdp_cmd("Target.getTargets", {})
targets = result.get("targetInfos", [])
for t in targets:
    url = t.get("url", "")
    target_id = t.get("targetId", "")
    is_amazon = "amazon.co.jp" in url
    is_product_page = "/dp/" in url or "/gp/product/" in url
    if is_amazon and not is_product_page and target_id:
        driver.execute_cdp_cmd("Target.closeTarget", {"targetId": target_id})
```

- `Target.getTargets` は**全Chromeウィンドウの全タブ**を返す（`driver.window_handles` は現在ウィンドウのみ）
- `/dp/` や `/gp/product/` を含まないAmazonタブ = 検索・一覧ページ → 閉じる
- `/dp/` を含むタブ = 商品詳細ページ → 残す（ユーザーが閲覧中の可能性）
- `_is_app_tab(url)` は `"/research" in url` AND `localhost/127.0.0.1/:5001` の両方を確認

---

## 注意事項

- Chromeは必ず `start.sh` 経由で起動すること（ポート9222のデバッグオプションが必要）
- `driver.quit()` は呼ばない（Chromeを閉じてしまうため）
- **タブ管理**：`fetch_amazon_from_url()` は `switch_to.new_window('tab')` で確実にタブとして開く。スクレイピング後、他にタブが残っていれば `driver.close()` で閉じる。最後の1タブの場合は閉じずに `localhost:5001/research` へ移動（ウィンドウが消えるのを防ぐ）
- **Amazonタブ自動クローズ（CDP）**：スクレイピング前に `Target.getTargets` で全タブを取得し、商品ページ以外のAmazonタブを `Target.closeTarget` で閉じる
- **2重実行防止**：`_research_fetch_lock`（threading.Lock）でサーバー側をロック。処理中に2件目のリクエストが来たら 429 を即返す
- **Excel保存先**：`config.EXCEL_BASE_DIR`（リサーチシートフォルダ）。スクレイピングデータは `config.OUTPUT_BASE_DIR`（リサーチ結果フォルダ）と分離されている
- **ファイルアクセス許可**：download・delete エンドポイントは `OUTPUT_BASE_DIR` と `EXCEL_BASE_DIR` の両方を許可ディレクトリとして確認する（分離前の古いExcelも引き続き操作可能）
- **JSでのパス受け渡し**：ファイルパスに日本語・スペースが含まれるため、HTML属性には `encodeURIComponent()` でエンコードして `data-path` 属性に格納し、イベントハンドラで `decodeURIComponent(this.dataset.path)` で復元する方式を採用（onclick属性への直接埋め込みはエスケープ問題が発生するため使わない）
- 旧形式（フラット保存）のExcelも `/research` のファイル一覧で表示・選択可能
