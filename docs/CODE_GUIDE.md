# コード解説書（エンジニア向け）

> 対象読者：このツールをメンテナンス・拡張するエンジニア  
> 最終更新：2026-05-30（フェーズ1.6完了・research_tool.py削除・excel_exporter.pyコメント更新）

---

## 1. プロジェクト構造

```
aucfan_tool/
├── app.py                  # Flaskアプリ本体・APIエンドポイント・バックグラウンドスレッド管理
├── config.py               # 全設定値（.envから読み込み）・CSSセレクター定義
├── scraper.py              # AucFan Seleniumスクレイパー（STEP 1 リスト取得 + 詳細取得）
├── seller_analyzer.py      # セラー分析スクレイパー（AucFanScraper継承、STEP 2）
├── data_manager.py         # セッションデータ管理・CSV/JSON保存・再開機能
├── image_processor.py      # 画像ダウンロード・pHash計算・グループ化・GDrive一括アップロード
├── gemini_client.py        # Gemini Vision/Text API による除外判定
├── sellers_master.py       # マスターセラーリスト管理（data/sellers_master.json）
├── pdf_exporter.py         # PDF自動生成（STEP完了時にCSV・HTML・PDFを保存）
├── excel_exporter.py       # Excelリサーチシート生成（商品カードの📗ボタンから呼び出し）
│                           #   現状はAucFanデータのみ出力（Amazon/1688は未実装）
│                           #   テンプレート（リサーチ_テンプレート.xlsx）を load_workbook() で読み込み
│                           #   値だけを書き込んで返す。書式変更はテンプレートを直接編集するだけでOK
│                           #   ★次回: 5シート構成に全面改修予定（Task #33）
├── build_template.py       # リサーチ_テンプレート.xlsx を新規生成するスクリプト
│                           #   `python3 build_template.py` で実行。書式を変更したいときはこの
│                           #   スクリプトを編集して再実行するか、生成済みファイルをExcelで直接編集
├── build_template_amazon.py # 5シートExcelテンプレート生成スクリプト（要全面書き直し）
│                           #   現状は旧2シート設計。5シート設計への改修が必要（Task #33）
├── リサーチ_テンプレート.xlsx  # Excelエクスポート用フォーマットテンプレート【現役・使用中】
│                           #   Excelで開いて書式を変更後に上書き保存するだけで次回エクスポートに反映
├── リサーチ_テンプレート_Amazon.xlsx  # 【旧設計・使用しない】2シート設計の残骸。削除または無視。
├── amazon_scraper.py       # Amazon商品ページデータ取得（Chromeリモートデバッグ接続）
├── scraper_1688.py         # 1688商品ページデータ取得（同接続方式）
│                           #   A+コンテンツ検出・group_id紐付け保存に対応
├── gdrive_uploader.py      # Google Drive API 直接アップロードモジュール（scraper Macのみ使用）
├── setup_gdrive_auth.py    # GDrive初回OAuth認証スクリプト（scraper Macで1回だけ実行）
├── switch_role.sh          # 役割切り替えスクリプト（scraper/reader/standalone）
│                           #   bash switch_role.sh scraper/reader/standalone で .env を自動更新
├── prompts.yaml            # Gemini用プロンプトテンプレート定義（外部ファイル）
├── rules.yaml              # 除外ルール一元管理ファイル（★メンテはここだけ）
│                           #   title_keywords    : タイトルキーワード除外リスト
│                           #   maker_keywords    : メーカー・ブランド名除外リスト
│                           #   trading_card_keywords / automotive_keywords : 判定補助
│                           #   custom_rules      : Gemini学習済みカスタムルール
├── .env                    # 環境変数（Git管理外）
├── .env.example            # .envのテンプレート
├── credentials.json        # GDrive OAuth クライアントシークレット（Git管理外・手動配置）
│                           #   Google Cloud Console でダウンロードした
│                           #   client_secret_xxx.apps.googleusercontent.com.json を
│                           #   credentials.json にリネームして配置する。
│                           #   scraper Mac のみ必要。GDRIVE_UPLOAD_ENABLED=false なら不要。
├── token.json              # GDrive アクセストークン（Git管理外・setup_gdrive_auth.pyが自動生成）
│                           #   setup_gdrive_auth.py 実行後に生成される。90日で期限切れになり
│                           #   自動更新されるが、期限切れ・削除時は再度 setup_gdrive_auth.py を実行。
├── requirements.txt        # Python依存ライブラリ
│
├── routes/                 # Flask Blueprint（APIルート分割）
│   ├── __init__.py
│   └── research.py         # /research・/api/research/* ルート（app.pyから分離済み）
│                           #   Blueprint名: research / インポート: Path, os, json, datetime, openpyxl 等
│                           #   新しいルートを追加する場合はここに @research_bp.route() を追記する
│
├── services/               # ビジネスロジック層（Flask非依存・単体テスト可能）
│   ├── __init__.py
│   ├── export.py           # HTML/PDF/Excel/CSV生成ロジック（app.pyから分離済み）
│   │                       #   _generate_export_html / _save_export_files / _build_export_html 等
│   ├── session.py          # セッション管理純粋関数（app.pyから分離済み）
│   │                       #   parse_session_info / list_sessions（running_names注入方式）
│   ├── scraping.py         # スクレイピングスレッドターゲット（app.pyから分離済み）
│   │                       #   run_keyword_scraping() — api_start()のスレッド処理を担当
│   │                       #   【方針】api_stop/resume/progressはapp.pyに残す（薄いグルーのため）
│   └── state.py            # アプリケーション状態クラス定義（app.pyから分離済み）
│                           #   ScraperState(_s1) / SellerState(_seller) / MasterState(_master)
│                           #   辞書互換インターフェース（__getitem__/__setitem__）付き
│                           #   global宣言を完全撤廃（app.py 3900行 → 2108行）
│
├── templates/
│   ├── index.html          # シングルページUI（Jinja2テンプレート）
│   └── research.html       # リサーチ追記ツールUI（app.pyのインライン文字列から分離済み）
│
├── static/
│   ├── app.js              # フロントエンドロジック（バニラJS）
│   └── style.css           # スタイルシート
│
├── data/
│   └── sellers_master.json # マスターセラーリスト（永続データ）
│
├── img_cache/              # 画像ローカルキャッシュ（スクレイピング完了後にGDriveへ一括アップロード）
│   └── セッション名/images/
│
└── docs/
    ├── USER_GUIDE.md        # ユーザー向けマニュアル
    ├── CODE_GUIDE.md        # 本ドキュメント
    ├── SETUP.md             # 環境構築手順
    ├── QUICKSTART.md        # クイックスタート
    └── HANDOVER.md          # 引き継ぎメモ（次回セッション向け・仕様確定内容を記録）
```

---

## 2. 主要ファイルの解説

### `config.py` — 設定の集約点

すべての設定値は `config.py` に集中管理されており、`.env` ファイルから `python-dotenv` 経由で読み込まれます。ハードコードの変更は不要で、`.env` の書き換えだけで動作を調整できます。

**除外ルールは `rules.yaml` で管理**：起動時に `_load_rules()` で `rules.yaml` を読み込み、`EXCLUDE_TITLE_KEYWORDS`・`EXCLUDE_MAKER_KEYWORDS`・`TRADING_CARD_KEYWORDS`・`AUTOMOTIVE_KEYWORDS` を生成します。コードに直接キーワードを書く必要はありません。

```python
# config.py 起動時の読み込みフロー
_RULES = _load_rules()                             # rules.yaml を読み込む
EXCLUDE_TITLE_KEYWORDS = _RULES.get("title_keywords", [])
EXCLUDE_MAKER_KEYWORDS = {w.lower() for w in _RULES.get("maker_keywords", [])}
TRADING_CARD_KEYWORDS  = set(_RULES.get("trading_card_keywords", []))
AUTOMOTIVE_KEYWORDS    = set(_RULES.get("automotive_keywords", []))
```

主な設定グループ：

| グループ | 変数例 | 用途 |
|---|---|---|
| Chrome接続 | `CHROME_DEBUG_PORT=9222` | Seleniumのリモートデバッグ接続先 |
| スクレイピング速度 | `MIN_DELAY`, `MAX_DELAY`, `MAX_PAGES` | 待機時間・最大ページ数 |
| 価格フィルタ | `MIN_PRICE=1000`, `MAX_PRICE=3000` | 一覧取得時の価格絞り込み |
| グループサイズ | `MIN_GROUP_SIZE=5`, `MASTER_SELLER_MIN_GROUP_SIZE=2` | 候補昇格・マスター追加の閾値 |
| pHash | `PHASH_THRESHOLD=5` | 同一商品判定の閾値（0=完全一致、大きいほど緩い） |
| Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL_VISION`, `GEMINI_RPM_LIMIT=14` | AI判定の設定 |
| Flask | `FLASK_PORT=5001`, `FLASK_HOST=0.0.0.0` | Webサーバー設定 |
| 出力先 | `OUTPUT_BASE_DIR=（Google Driveパス）` | セッションフォルダの親ディレクトリ。デフォルトは `~/Library/CloudStorage/.../AucFanToolData/リサーチ結果`。Google Drive未接続時はローカルの `リサーチ結果/` にフォールバック |

**CSS セレクター (`SELECTORS` 辞書)**: AucFanのHTML構造が変わった際はここを更新します。`list`キー配下が一覧ページ用、`detail`キー配下が詳細ページ用で、それぞれ候補セレクターをリストで持ちます（先頭から順に試行します）。

---

### `data_manager.py` — データの中核

`DataManager` クラスはスクレイピング中のデータをメモリ上に保持し、定期的にディスクへ書き出します。1つのスクレイピングセッション＝1つの `DataManager` インスタンスに対応します。

**主要メソッド**：

| メソッド | 説明 |
|---|---|
| `add_item(item)` | 商品を追加。`item_id` を自動生成して返す |
| `update_item(item_id, updates)` | 商品データを部分更新 |
| `remove_items(item_ids)` | 指定アイテムセットをデータから削除（中古セラースキップ時に使用） |
| `assign_group(item_ids, group_id)` | pHash結果のグループIDを商品に割り当て |
| `promote_candidates(min_group_size)` | グループサイズに応じてステータスを `candidate` / `next_candidate` に昇格 |
| `save_all()` | `progress.json` + `items.json` + `results.csv` を一括保存 |
| `load_previous_session()` | 前回の `progress.json` / `items.json` を読み込んで再開 |
| `get_stats()` | グループ単位のステータス集計を返す |
| `save_amazon_data(group_id, data)` | Amazonデータを `amazon_data.json` に group_id をキーとして保存 |
| `get_amazon_data(group_id)` | 指定 group_id のAmazonデータを返す。未取得の場合は `None` |
| `get_all_amazon_data()` | 全group_idのAmazonデータを dict で返す |

**Amazonデータ保存**（`amazon_data.json`）：`save_amazon_data(group_id, data)` で group_id ごとにAmazonデータを保存します。`data` は `amazon_scraper.fetch_amazon_product()` の戻り値（ASIN・タイトル・価格・評価・レビュー数・A+フラグ・URL・箇条書き・説明・仕様等）に `saved_at` タイムスタンプを付加したものです。

**★次回追加予定（Task #36）**：1688データ保存メソッド。1group_idに対してショップのリスト（複数ショップ追記式）を管理する `save_1688_shop(group_id, shop_data)` / `get_1688_data(group_id)` / `reset_1688_data(group_id)` を追加する。

**セッションフォルダ作成**: `make_output_dir(keyword, step=1)` 関数（クラス外）がフォルダを作成し、`(out_dir: Path, session_id: str)` を返します。新命名規則は `S{step}_YYYYMMDD_NN[_keyword]/`。同日・同ステップの既存フォルダ数を走査して連番を決定します。

**スレッドセーフ**: すべてのデータ操作は内部の `threading.Lock` で保護されています。

---

### `scraper.py` — Seleniumスクレイパー（STEP 1）

`AucFanScraper` クラスがコアのスクレイピングロジックを担います。既存のChromeブラウザにリモートデバッグで接続し（`chrome://new-tab-page` を開いた状態で起動されたChrome）、AucFanの検索結果を順次取得します。

**主要な内部フロー**：

1. `connect()` — `selenium.webdriver.Remote` でポート9222に接続
2. `scrape_list_pages(keyword, url)` — 検索一覧を全ページ走査。各商品カードを `_parse_item_card()` で解析し、価格フィルタ・タイトルキーワード除外・メーカー名除外・商品状態フィルタを適用。STEP 2/3モードでは `_seller_used_count` を累積し、`SELLER_USED_SKIP_THRESHOLD` 超過時に `_seller_skipped_by_used=True` をセットして早期終了する
3. `_parse_item_card()` — 商品カードからタイトル・価格・セラーID・画像URL・商品状態等を抽出。各種除外判定もここで実行。STEP 2/3モード（`skip_price_filter=True`）かつ `SELLER_NEW_ONLY=true` のとき、`<dt>商品状態</dt><dd>` から状態テキストを取得し、新品系ワード（新品・未使用・未開封・未着用）以外を除外する。除外件数は `_seller_used_count` に累積される
4. `run_phash_grouping()` — pHash計算後にハミング距離でグループ化し `assign_group()` を呼ぶ
5. `scrape_detail_pages()` — 候補商品の詳細ページを個別取得（STEP 1でのみ使用）
6. `_run_gemini_checks()` — グループサイズが `VISION_MIN_GROUP_SIZE` 以上のグループに対してGemini Vision判定を実行

**AucFanログイン状態チェックと待機**：

各ページ取得の直前に `_is_logged_in()` を呼び出し、AucFanがログアウト状態（「ゲストさん」文言をページソースから検索）を検知した場合は `_wait_for_login()` を呼んで待機する。

| メソッド | 説明 |
|---|---|
| `_is_logged_in()` | `driver.page_source` に「ゲストさん」が含まれていれば `False`（未ログイン）を返す。ドライバーエラー時は `True`（ログイン済みと仮定）にフォールバック |
| `_wait_for_login(resume_url)` | `login_required` ステータスをUIに通知してターミナルに警告を表示。`login_check_event` が set されるか30秒経過するたびにAucFanトップページでログイン確認。ログイン復帰を検知したら `resume_url` に戻って `True` を返す。`stop_event` セット時は `False` を返す |

`login_check_event: threading.Event`（`__init__` の任意引数）が set されると30秒待機を中断して即時確認を実行する。UIの「🔄 今すぐ確認して再開」ボタン → `/api/login_check` → `_login_check_event.set()` がトリガー経路。STEP1/2/3で共通の1つのEventを使用する。

一覧取得ループ（`_scrape_list_pages`）と詳細取得ループ（`_scrape_detail_pages`）の両方にログインチェックが組み込まれており、STEP1〜3すべてで動作する。

**進捗カウンター**:

`_total_items` と `_processed_items` の2つのインスタンス変数でスクレイピング対象の総件数と処理済み件数をそれぞれ追跡します。`app.py` の `scrape_status` レスポンスに `processed_items` フィールドとして公開され、フロントエンドの `updateProgressUI()` で「X件 / Y件処理済み」カウンター表示に使われます。スクレイピング完了時には `=== STEP 1 スクレイピング完了 === 全N件処理` というログをターミナルに出力します。

`stop_event: threading.Event` が set されると各ループで検知して安全に停止します。

---

### `seller_analyzer.py` — セラー分析（STEP 2）

`AucFanScraper` を継承した `SellerAnalyzer` クラスです。複数のセラーURLを1セッションで順番にスクレイピングし、セラーごとにインクリメンタルpHashグループ化を行います。

**特徴**：

- `scrape_detail=False`（デフォルト）のため詳細ページ取得はスキップ。一覧取得のサムネールだけでpHash判定を行います
- `skip_price_filter = True` に設定されるため価格フィルタは無効（セラーの全商品を対象とする）
- セラーごとに `on_seller_progress(index, status)` コールバックが呼ばれ、フロントエンドの進捗表示に使われます
- STEP 2の `min_group_size=1` で `promote_candidates()` を呼ぶため、全商品が `candidate` になります（単品でも表示対象）
- スクレイピング完了時には `=== STEP 2 スクレイピング完了 === 全N件処理` というログをターミナルに出力します。STEP 3（マスターリスト横断）の場合は `=== STEP 3 スクレイピング完了 === 全N件処理` が同様に出力されます
- `login_check_event` 引数（省略可）を `super().__init__()` 経由で `AucFanScraper` に渡すことで、ログイン即時確認ボタンがSTEP2/3でも動作します
- `run()` のオーバーライド末尾で `self.img.upload_images_to_gdrive()` を呼び出し、スクレイピング完了後に画像をGDriveへ一括アップロードします（`AucFanScraper.run()` と同様。STEP3も同じ `SellerAnalyzer.run()` 経由で実行されるため対応済み）

**中古セラー自動スキップ**：

各セラーのスクレイピング開始時に `_seller_used_count` と `_seller_skipped_by_used` をリセットします。`_parse_items_from_page()` が商品状態フィルタで除外した件数をページをまたいで累積し、`SELLER_USED_SKIP_THRESHOLD`（デフォルト3）を超えると `_seller_skipped_by_used=True` をセットして一覧取得ループを即座に終了します。`seller_analyzer.py` 側でこのフラグを検出し、`dm.remove_items()` でそのセラーの取得済みデータを全削除・コールバックで `"used_skip"` ステータスを通知して次のセラーへ進みます。

**インクリメンタルpHashグループ化 + 最終グループ代表マージ**：

各セラーのスクレイピング完了後に `_incremental_phash_group(new_item_ids)` を呼び出し、その**セラーで新たに追加された商品だけ**を既存グループ代表と比較してマッチングします（計算量 O(新規件数 × グループ数)）。全セラー完了後は `_merge_groups_by_phash()` でグループ代表ハッシュ同士のみを比較して似たグループをまとめます（計算量 O(グループ数²)）。全アイテムを比較する `group_by_phash()` と異なり件数上限がなく、42,500件超のセッションでも数秒〜数十秒で完了します。

**`_merge_groups_by_phash()` の最適化（グループ化高速化）**：

旧実装では比較ループ内で毎回 `imagehash.hex_to_hash()` を呼んでいたため、5,000グループの場合最大約1,250万回の文字列→オブジェクト変換が発生し「止まっているように見える」問題があった。現在は以下の最適化を実施済み：

- **事前一括変換**: ループ前に全代表ハッシュ文字列を `img.str_to_phash()` で imagehash オブジェクトに変換。ループ内では `img.is_same_image_obj()` でオブジェクト同士を直接比較（文字列パース不要）
- **進捗ログ**: 500グループごとにターミナルとlogに進捗を出力（「止まっているように見える」問題を解消）
- **停止チェック**: 100グループごとに `stop_event` を確認し、停止リクエストに応答

---

### `image_processor.py` — 画像処理

`ImageProcessor` クラスが画像のダウンロードとpHash計算を担います。

- サムネール画像を `requests` でダウンロードし、セッションの `images/` ディレクトリに保存
- `imagehash.phash()` でPerceptual Hash（pHash）を64ビット文字列として計算
- `group_by_phash(items)` がハミング距離 ≤ `PHASH_THRESHOLD` の商品を同一グループとみなしてクラスタリング

**GDriveアップロードとの関係（`gdrive_uploader.py`）**：

`gdrive_uploader.py` はメインアプリ（Flask / `app.py`）からは直接呼ばれません。
`image_processor.py` 内の2つのメソッドから自動で呼び出されます。

| メソッド | 呼び出しタイミング | 動作 |
|---|---|---|
| `_copy_to_gdrive(local_path, filename)` | 画像1枚ダウンロード直後 | 1枚ずつリアルタイムアップロード |
| `upload_images_to_gdrive()` | スクレイピング完了時（`scraper.py` の `run()` 終了後） | セッション内の全画像をまとめてアップロード |

どちらも `GDRIVE_UPLOAD_ENABLED=true` かつ `SITE_ROLE=scraper` の場合のみ実行されます。
それ以外の場合（reader機・standalone）は何もせず即リターンするため、`gdrive_uploader.py` を意識する必要はありません。

アップロード先のフォルダ構成：
```
GDrive: AucFanToolData/リサーチ結果/{セッション名}/images/{ファイル名}
```
セッション名はS1/S2/S3いずれも対象です（S2専用ではありません）。

**グループ代表マージ向け高速比較メソッド**：

| メソッド | 説明 |
|---|---|
| `str_to_phash(hash_str)` | pHash文字列を imagehash オブジェクトに変換して返す。変換失敗時は `None`。大量比較前に一括変換することで `is_same_image()` の hex_to_hash() 重複呼び出しを回避できる |
| `is_same_image_obj(obj1, obj2)` | 事前変換済み imagehash オブジェクト同士のハミング距離を比較。文字列パースなしで高速動作。どちらかが `None` なら `False` を返す |

`_merge_groups_by_phash()` はこの2メソッドを使って事前一括変換 → オブジェクト比較の流れで実行する（文字列比較より大幅に高速）。

---

### `gemini_client.py` — AI判定

`GeminiClient` クラスがGemini APIとのやり取りを管理します。プロンプトは `prompts.yaml` から読み込まれ、ファイルが存在しない場合はコード内のデフォルトプロンプトにフォールバックします。

**`rules.yaml` の `custom_rules` を自動注入**：

`check_excluded_category()` の呼び出し時に `_build_custom_rules_prompt()` で `rules.yaml` の `custom_rules` セクションを読み込み、Geminiの除外判定プロンプトに自動追加します。これにより `custom_rules` に書いたカスタムルールがスクレイピング中のGemini判定に反映されます。

```python
# custom_rules の注入フロー（gemini_client.py 内）
custom_section = _build_custom_rules_prompt()   # rules.yaml から生成
# 例: 「【ユーザー定義の追加除外ルール】\n- 「フライパン」: 衛生リスク商品のため除外」
prompt = base_prompt.replace("商品タイトル: {title}", f"{custom_section}\n商品タイトル: {title}")
```

**主要メソッド**：

| メソッド | 使用モデル | 用途 |
|---|---|---|
| `check_excluded_category(title)` | `GEMINI_MODEL_TEXT` | 絶対除外カテゴリ判定（custom_rules も自動注入） |
| `check_needs_review(title)` | `GEMINI_MODEL_TEXT` | 要確認フラグ判定（車の保安部品等） |
| `check_branded(title)` | `GEMINI_MODEL_TEXT` | 有名ブランド品判定 |
| `check_oversized(title, size_info)` | `GEMINI_MODEL_TEXT` | 大型サイズ商品判定 |
| `check_same_product_vision(image_paths)` | `GEMINI_MODEL_VISION` | 複数画像が同一商品か判定 |
| `classify_item_full(title, image_path)` | Vision / Text | 商品の総合判定（Vision優先、なければText3回） |
| `analyze_ng_reason(reason)` | `GEMINI_MODEL_TEXT` | 手動NG理由を分析してカテゴリ・説明・除外キーワード候補を返す |

**`analyze_ng_reason()` の仕様**：

ユーザーが手動でNG入力した理由テキストをGeminiに送り、除外ルール整理に役立つ情報を返します。

```python
# 入力
gc.analyze_ng_reason("フライパンなのでNG")

# 出力（dict）
{
  "category": "衛生リスク商品",
  "explanation": "フライパンは食品と直接接触する調理器具のため、中古品は衛生リスクがある",
  "keywords": ["フライパン", "鍋", "調理器具"]
}
```

**レート制限**: `GEMINI_RPM_LIMIT=14` でリクエスト間隔を自動調整します（無料枠15RPMに対して安全マージンを設けています）。`GEMINI_ENABLED=false` または `GEMINI_API_KEY` 未設定の場合はAPI呼び出しをスキップしてpHashのみで動作します。

**エラー処理とエラーステータス管理**:

API呼び出し時に発生した例外メッセージを文字列で検査し、エラー種別（`type`）を判定して `_last_error` に格納します。判定ロジックは以下の優先順位で行います。

```python
# gemini_client.py 内のエラー種別判定ロジック（概略）
error_str = str(e).lower()
if "429" in error_str or "resource_exhausted" in error_str:
    error_type = "rate_limit"
elif "503" in error_str or "service_unavailable" in error_str:
    error_type = "service_unavailable"
elif "500" in error_str or "internal" in error_str:
    error_type = "internal_error"
elif "403" in error_str or "permission_denied" in error_str:
    error_type = "permission_denied"
elif "400" in error_str or "invalid_argument" in error_str:
    error_type = "invalid_argument"
else:
    error_type = "unknown"
```

`_last_error` は辞書形式 `{"type": "...", "message": "...", "timestamp": "..."}` で保持されます。`get_last_error()` メソッドで取得・クリアできます。

**レート制限フラグ管理**:

`_last_error` とは別に、レート制限の発生を追跡する専用の状態変数を持ちます。

| 変数 / メソッド | 型 | 役割 |
|---|---|---|
| `_rate_limit_hit` | `bool` | レート制限（429）が発生中かどうかのフラグ |
| `_rate_limit_time` | `float \| None` | レート制限が最後に発生した時刻（`time.time()` の値） |
| `_rate_limit_lock` | `threading.Lock` | 上記2変数への同時アクセスを防ぐロック |
| `get_rate_limit_status()` | `dict` | `{"hit": bool, "since": str \| None}` 形式で現在の状態を返す。`app.py` の `/api/gemini_status` がこれを呼び出す |
| `reset_rate_limit_flag()` | `None` | `_rate_limit_hit` を `False` に戻す。スクレイピング開始時・ユーザーによる手動リセット時に呼ばれる |

`_rate_limit_hit` が `True` の間は新たなGemini APIリクエストを抑制し、レート制限エラーが連続してバナーが表示され続けることを防ぎます。一定時間（デフォルト60秒）が経過するか `reset_rate_limit_flag()` が呼ばれると次回リクエスト時に自動的にリセットされます。

---

### `sellers_master.py` — マスターリスト管理

`SellersMaster` クラスが `data/sellers_master.json` の読み書きを担います。アプリ起動時に `app.py` でシングルトンとしてインスタンス化されます。

**データ構造**（1エントリ）：

```json
{
  "seller_id": "abc123",
  "first_seen_date": "2026-05-01",
  "last_scraped_date": null,
  "source_keyword": "バフ",
  "candidates_count": null
}
```

**主要メソッド**：

| メソッド | 説明 |
|---|---|
| `upsert_sellers(seller_ids, source_keyword)` | 新規セラーを追記（重複はスキップ） |
| `update_scraped(seller_id, candidates_count)` | STEP 3完了後に `last_scraped_date` と `candidates_count` を書き込む |
| `get_unscraped()` | `last_scraped_date` が null のセラーのみ返す（STEP 3の対象リスト） |
| `merge_from_file(file_path)` | 外部の `sellers_master.json` を読み込んで現在のリストにマージする |
| `delete_seller(seller_id)` | 指定セラーを削除 |
| `clear_all()` | 全件削除 |

**`merge_from_file(file_path)` の仕様**:

- **引数**: `file_path: str | Path` — インポートするJSONファイルのパス
- **戻り値**: `dict` — `{"added": int, "skipped": int, "total": int}` 形式。`added` は新規追加件数、`skipped` は既存エントリとの重複によりスキップした件数、`total` はマージ後の全件数
- **重複処理**: `seller_id` をキーとして照合。既存エントリが存在する場合はスキップし、インポート元の値で上書きしません（`first_seen_date` 等の初期データを保持するため）
- **スレッドセーフ**: 内部の `threading.Lock` を使って処理します

すべての操作で `threading.Lock` が使われており、スレッドセーフです。

**Google Drive連携における参照先**: `SellersMaster` は初期化時に `config.SELLERS_MASTER_PATH` を参照してJSONファイルのパスを決定します。`SELLERS_MASTER_PATH` が空文字の場合は `config.OUTPUT_BASE_DIR / "sellers_master.json"` をフォールバックとして使用します。これにより、`.env` の `OUTPUT_BASE_DIR` と `SELLERS_MASTER_PATH` を Google Drive のパスに変更するだけで、ファイルの読み書き先が自動的にGoogle Driveに切り替わります。

---

### Google Drive連携の技術的説明

複数のMacでリサーチデータを共有するための仕組みです。コードの変更は不要で、`.env` の `SITE_ROLE` と `GDRIVE_UPLOAD_ENABLED` を変更するだけで動作します。

**`config.py` での GDriveパス自動検出 (`_find_gdrive_aucfan_root`)**:

`config.py` に `_find_gdrive_aucfan_root()` 関数があり、以下の順序で AucFanToolData のパスを自動検出します。Mac のユーザー名が違っても `Path.home()` を使うため問題ありません。

```python
def _find_gdrive_aucfan_root() -> str:
    home = Path.home()
    # 1. ミラーリングモード: ~/マイドライブ*/AucFanToolData
    for candidate in sorted(home.glob("マイドライブ*")):
        p = candidate / "AucFanToolData"
        if p.exists():
            return str(p)
    # 2. ストリーミングモード: ~/Library/CloudStorage/GoogleDrive-*/マイドライブ/AucFanToolData
    cloud = home / "Library" / "CloudStorage"
    if cloud.exists():
        for gd in sorted(cloud.glob("GoogleDrive-*")):
            p = gd / "マイドライブ" / "AucFanToolData"
            if p.exists():
                return str(p)
    return None

GDRIVE_EMAIL = os.getenv("GDRIVE_EMAIL", "")   # ← .envで設定（メールアドレスをコードに書かない）

_gdrive_fallback = (
    f"~/マイドライブ（{GDRIVE_EMAIL}）/AucFanToolData"
    if GDRIVE_EMAIL
    else "~/AucFanToolData"
)
_GDRIVE_ROOT = _find_gdrive_aucfan_root() or os.path.expanduser(_gdrive_fallback)
_GDRIVE_BASE = os.path.join(_GDRIVE_ROOT, "リサーチ結果")
OUTPUT_BASE_DIR = os.getenv("OUTPUT_BASE_DIR", _GDRIVE_BASE)
```

`.env` に `OUTPUT_BASE_DIR` を明示した場合はそちらが優先（スタンドアロン運用時に `OUTPUT_BASE_DIR=リサーチ結果` と指定するケースなど）。

**`GDRIVE_EMAIL` について（セキュリティ対応）**:

メールアドレスをコードにハードコードするとpublic GitHubリポジトリに露出するため、`.env` で管理する方式に変更した。`_find_gdrive_aucfan_root()` が自動検出できた場合はこの値は使われない。自動検出に失敗したときのフォールバックパス構築にのみ使用される。`.env.example` には `GDRIVE_EMAIL=your_google_account@gmail.com` として記載されている。

**3つの動作モード**:

| モード | `SITE_ROLE` | `GDRIVE_UPLOAD_ENABLED` | 画像保存先 | `credentials.json` |
|---|---|---|---|---|
| scraper（十王Mac） | `scraper` | `true` | GDrive API 経由でアップロード | 必要 |
| reader（守谷Mac） | `reader` | `false` | GDriveミラーリングから直接参照 | 不要 |
| standalone（1台完結） | `scraper` | `false` | ローカル `リサーチ結果/` | 不要 |

**`SITE_ROLE` による `LOCAL_IMAGE_CACHE_DIR` の自動切り替え**:

```python
if SITE_ROLE == "reader":
    _default_image_cache = _GDRIVE_BASE  # ミラーリング済みフォルダを画像ソースとして使う
else:
    _default_image_cache = str(Path(__file__).parent / "img_cache")  # ローカルキャッシュ
LOCAL_IMAGE_CACHE_DIR = Path(os.path.expanduser(
    os.getenv("LOCAL_IMAGE_CACHE_DIR", _default_image_cache)
))
```

`app.py` の画像配信エンドポイント `/images/<session>/<path>` は `config.LOCAL_IMAGE_CACHE_DIR` を基点として `send_from_directory()` で画像を返すため、reader Mac では GDrive ミラーリングフォルダから直接画像が配信されます。

**`data_manager.py` の `make_output_dir()`**:

セッションフォルダを作成する `make_output_dir(keyword, step=1)` は `config.OUTPUT_BASE_DIR` を親ディレクトリとして使います。`app.py` の `_list_sessions()` も同様のロジックで同じ親ディレクトリを走査します。

**`sellers_master.py` の参照先**:

`SellersMaster.__init__()` が `config.SELLERS_MASTER_PATH` を読み取り、そのパスに対して読み書きを行います。2台のMacが同じGoogle Driveパスを参照することで、マスターセラーリストが自動的に共有されます。

---

### `app.py` — Flaskアプリ・コントローラー

Flask ルート定義とバックグラウンドスレッドの管理が主な役割です。

**グローバル状態変数**：

```python
_scraper_thread      # STEP 1スクレイピングスレッド
_stop_event          # STEP 1停止イベント
_data_manager        # 現在のSTEP 1セッションのDataManager
_seller_state        # STEP 2状態辞書（running, phase, thread, dm, session_id ...）
_master_state        # STEP 3状態辞書（running, phase, thread, dm, session_id ...）
_sellers_master      # SellersMasterシングルトン
_login_check_event   # ログイン即時確認トリガー（threading.Event）。UIの「今すぐ確認して再開」ボタンが set() する。STEP1/2/3で共通。
```

**主要APIエンドポイント**：

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `GET /` | GET | メインUI（index.html）を返す |
| `/api/start` | POST | STEP 1スクレイピング開始 |
| `/api/stop` | POST | STEP 1スクレイピング停止 |
| `/api/progress` | GET | SSEストリームで進捗を配信 |
| `/api/groups` | GET | グループ一覧（グリッド表示用） |
| `/api/sessions` | GET | セッション一覧（`?step=1|2|3` でフィルタ可） |
| `/api/sessions/<name>/load` | POST | 指定セッションをグリッドに読み込む |
| `/api/sessions/<name>` | DELETE | セッションフォルダを削除 |
| `/api/current_session` | GET | 現在グリッドに表示中のセッション情報 |
| `/api/load_csv` | POST | CSVファイルをアップロードしてセッション作成 |
| `/api/seller/start` | POST | STEP 2スクレイピング開始 |
| `/api/seller/stop` | POST | STEP 2停止 |
| `/api/seller/progress` | GET | STEP 2進捗SSE |
| `/api/master/start` | POST | STEP 3スクレイピング開始 |
| `/api/master/stop` | POST | STEP 3停止 |
| `/api/master/progress` | GET | STEP 3進捗SSE |
| `/api/master_list` | GET | マスターセラーリスト取得 |
| `/api/master_list/delete` | POST | マスターリストから指定セラーを削除 |
| `/api/master_list/clear` | POST | マスターリストを全件削除 |
| `/api/master/merge` | POST | 外部の `sellers_master.json` をマージ。`multipart/form-data` でファイルを受け取り `SellersMaster.merge_from_file()` に委譲する。レスポンス: `{"added": int, "skipped": int, "total": int}` |
| `/api/login_check` | POST | UIの「今すぐ確認して再開」ボタンから呼び出す。`_login_check_event.set()` してスクレイパーの30秒待機ループを即時起動する。STEP1/2/3共通 |
| `/api/export/csv` | GET | 現在セッションをCSVエクスポート |
| `/api/export/html` | GET | 現在セッションをHTMLエクスポート（Mac用・画像はサーバー経由） |
| `/api/export/excel/<group_id>` | POST | 指定グループ1件分のExcelリサーチシートを生成し `config.OUTPUT_BASE_DIR/商品タイトル_リサーチ.xlsx` として保存。レスポンス: `{"success": true, "filename": "..."}` |
| `/api/gemini_status` | GET | 直近のGemini APIエラー情報を返す（フロントエンドのポーリング用） |
| `/api/group/<id>/status` | POST | グループのステータスを更新。`{"status": "ng", "ng_reason": "..."}` で手動NG理由を `exclude_reason` フィールドに保存。`gemini_source=manual` も記録 |
| `/api/ng/analyze` | POST | 手動NG理由テキストをGeminiで分析。`{"reason": "フライパンなのでNG"}` を送ると `{"category": "...", "explanation": "...", "keywords": [...]}` を返す |

**進捗レスポンスへの `processed_items` フィールド**:

`scrape_status`（STEP 1）、`seller_status`（STEP 2）、`master_status`（STEP 3）の各ステータスレスポンスには `processed_items` フィールドが含まれます。これはスクレイパー側の `_processed_items` カウンター値であり、`app.js` の `updateProgressUI()` / `fetchSellerStatus()` / `fetchMasterStatus()` がこの値を読み取って「X件 / Y件処理済み」カウンターを画面上に更新します。スクレイピング完了時には `app.js` がこのフィールドをもとに緑色の「✅ スクレイピング完了（N件処理）」バナーを表示します（✕ボタンで閉じられます）。

**`/api/gemini_status` エンドポイント仕様**:

`app.js` がスクレイピング中に定期ポーリング（約5秒間隔）するエンドポイントです。`GeminiClient.get_last_error()` の結果をそのままJSONで返します。エラーがない場合は `{"error": null}` を返します。

```json
// エラーあり時のレスポンス例
{
  "error": {
    "type": "rate_limit",
    "message": "429 RESOURCE_EXHAUSTED: ...",
    "timestamp": "2026-05-06T12:34:56"
  }
}
```

エラー種別（`type`）とフロントエンドの表示内容の対応：

| `type` | HTTPステータス / gRPCコード | バナー表示 | バナー色 |
|---|---|---|---|
| `rate_limit` | 429 / RESOURCE_EXHAUSTED | ⚠️ Gemini APIレート制限超過。無料枠使い切りの可能性があります | オレンジ〜赤 |
| `service_unavailable` | 503 / SERVICE_UNAVAILABLE | ⚠️ Gemini APIが一時的に混雑しています。しばらく待って再試行してください | 黄色 |
| `internal_error` | 500 / INTERNAL | ⚠️ Gemini API内部エラーが発生しました。判定スキップで続行中 | 黄色 |
| `permission_denied` | 403 / PERMISSION_DENIED | 🔴 Gemini APIキーの権限エラー。APIキーを確認してください | 赤 |
| `invalid_argument` | 400 / INVALID_ARGUMENT | ⚠️ Gemini API入力エラー（画像不正など）。スキップして続行中 | 黄色 |

`app.js` 側では `pollGeminiStatus()` 関数がポーリングを担い、エラーを検出するとDOM上部に `#gemini-error-banner` 要素を動的に生成して表示します。✕ボタンのクリックでバナーを閉じます（次のポーリングで再度エラーが検出された場合は再表示されます）。

**セッション一覧ヘルパー `_list_sessions(step=None)`**:
`リサーチ結果/` 配下のフォルダを走査し、`_parse_session_info(name)` でメタデータを抽出したリストを返します。`is_running` フィールドは各グローバル状態変数を参照して動的にセットされます。

---

## 3. データフロー

```
[ユーザーがキーワード入力]
        │
        ▼
  STEP 1: AucFanScraper
  ┌─────────────────────────────────┐
  │ 1. scrape_list_pages()          │
  │    └─ 各商品カードをparse       │
  │       → 価格フィルタ            │
  │       → タイトルキーワード除外  │
  │       → メーカー名除外          │
  │       → DataManager.add_item()  │
  │                                 │
  │ 2. run_phash_grouping()         │
  │    └─ 画像DL → pHash計算        │
  │       → ハミング距離クラスタ    │
  │       → assign_group()          │
  │       → promote_candidates()    │
  │                                 │
  │ 3. scrape_detail_pages()        │
  │    └─ 候補商品の詳細URL取得     │
  │       → 箱サイズ取得            │
  │                                 │
  │ 4. _run_gemini_checks()         │
  │    └─ Vision判定(グループ単位)  │
  │                                 │
  │ 5. upsert_sellers()             │
  │    └─ 候補セラーをマスターへ    │
  │       (MASTER_SELLER_MIN_GROUP  │
  │        _SIZE以上のグループのみ) │
  └─────────────────────────────────┘
        │
        │  results.csv / items.json
        ▼
  STEP 2: SellerAnalyzer (任意)
  ┌─────────────────────────────────┐
  │ 複数セラーURLを順番に           │
  │ scrape_list_pages() で取得      │
  │ → セラー完了ごとに              │
  │    _incremental_phash_group()   │
  │    （新規商品 vs 既存グループ）  │
  │ → 1セッションに集約して保存     │
  └─────────────────────────────────┘
        │
        ▼
  STEP 3: マスターセラーリサーチ
  ┌─────────────────────────────────┐
  │ sellers_master.get_unscraped()  │
  │ → 未スクレイプセラーを取得      │
  │ → 各セラーURLを1件ずつ          │
  │    scrape_list_pages()          │
  │ → pHashグループ化               │
  │ → Gemini Vision判定             │
  │ → update_scraped()で完了マーク  │
  └─────────────────────────────────┘
        │
        ▼
  [マスターリストタブ]
  data/sellers_master.json に永続化
```

---

## 4. 環境変数一覧（.env）

| 変数名 | デフォルト値 | 説明 |
|---|---|---|
| `GEMINI_API_KEY` | `""` | Gemini APIキー（必須）|
| `GEMINI_ENABLED` | `true` | `false` にするとGeminiをスキップしてpHashのみ動作 |
| `GEMINI_MODEL_VISION` | `gemini-3.5-flash` | 画像判定に使用するGeminiモデル |
| `GEMINI_MODEL_TEXT` | `gemini-3.5-flash` | テキスト判定に使用するGeminiモデル |
| `GEMINI_RPM_LIMIT` | `14` | 1分あたりリクエスト上限（無料枠=15、安全マージンで14） |
| `CHROME_DEBUG_HOST` | `127.0.0.1` | Chromeリモートデバッグホスト |
| `CHROME_DEBUG_PORT` | `9222` | Chromeリモートデバッグポート |
| `MIN_DELAY` | `3.0` | ページ間の最小待機秒数 |
| `MAX_DELAY` | `5.0` | ページ間の最大待機秒数 |
| `MAX_PAGES` | `500` | 1セッションの最大取得ページ数 |
| `ITEMS_PER_PAGE` | `50` | 1ページあたりの商品件数 |
| `PAGE_LOAD_TIMEOUT` | `30` | ページロードタイムアウト（秒） |
| `MIN_PRICE` | `1000` | 取得対象の最低価格（円） |
| `MAX_PRICE` | `3000` | 取得対象の最高価格（円） |
| `MIN_GROUP_SIZE` | `5` | `candidate`（仕入れ候補）に昇格するグループ最小件数 |
| `MIN_NEXT_CANDIDATE_SIZE` | `4` | `next_candidate`（次期候補）に昇格するグループ最小件数 |
| `SELLER_DETAIL_MIN_GROUP` | `3` | セラー分析で詳細取得・Gemini判定する最小グループ件数 |
| `VISION_MIN_GROUP_SIZE` | `4` | pHash後にVision判定を行うグループの最小件数 |
| `MASTER_SELLER_MIN_GROUP_SIZE` | `2` | マスターリストに追加するセラーの最小グループサイズ |
| `PHASH_THRESHOLD` | `5` | pHash同一判定のハミング距離閾値 |
| `IMAGE_DOWNLOAD_TIMEOUT` | `10` | 画像ダウンロードタイムアウト（秒） |
| `MAX_BOX_L` | `45` | 除外する箱サイズ（縦cm） |
| `MAX_BOX_W` | `35` | 除外する箱サイズ（横cm） |
| `MAX_BOX_H` | `20` | 除外する箱サイズ（高さcm） |
| `FLASK_PORT` | `5001` | FlaskサーバーのListenポート |
| `FLASK_HOST` | `0.0.0.0` | FlaskサーバーのListenホスト（`0.0.0.0`でLAN公開） |
| `SITE_ROLE` | `scraper` | 動作モード。`scraper`=スクレイピング機（十王Mac・standalone）/ `reader`=閲覧専用機（守谷Mac）。`reader` のとき `LOCAL_IMAGE_CACHE_DIR` が GDriveミラーリングフォルダに自動切り替わる |
| `GDRIVE_UPLOAD_ENABLED` | `true` | `true`: scraper Mac が GDrive API で画像・PDFをアップロード（`credentials.json` 必要）。`false`: アップロード無効（reader機・standalone時） |
| `OUTPUT_BASE_DIR` | `（自動検出）` | セッションフォルダの保存先。`config.py` の `_find_gdrive_aucfan_root()` が GDrive パスを自動検出するため通常設定不要。standalone 時のみ `OUTPUT_BASE_DIR=リサーチ結果` を追加 |
| `LOCAL_IMAGE_CACHE_DIR` | `（SITE_ROLEに応じて自動設定）` | アプリが画像を読む基底ディレクトリ。`SITE_ROLE=scraper` なら `img_cache/`、`reader` なら GDriveミラーリング済みフォルダに自動設定。手動上書きしたい場合のみ `.env` に追加 |
| `SELLERS_MASTER_PATH` | `（自動検出）` | マスターセラーリストのフルパス。GDriveパスを自動検出するため通常設定不要。standalone 時のみ `SELLERS_MASTER_PATH=data/sellers_master.json` を追加 |
| `EXCLUDE_TITLE_KEYWORDS` | `""` | （非推奨）追加の除外タイトルキーワード。`rules.yaml` の `title_keywords` に追記する方法を推奨 |
| `EXCLUDE_MAKER_KEYWORDS` | `""` | （非推奨）追加の除外メーカー名。`rules.yaml` の `maker_keywords` に追記する方法を推奨 |
| `SELLER_SCRAPE_DETAIL` | `false` | `true` にするとSTEP 2でも詳細ページを取得する（非推奨・低速） |
| `SELLER_NEW_ONLY` | `true` | STEP 2/3で「商品状態」が新品系ワード以外の商品を除外する。`false` で無効化 |
| `SELLER_NEW_CONDITIONS` | `新品,未使用,未開封,未着用` | 新品とみなす商品状態ワード（カンマ区切り） |
| `SELLER_USED_SKIP_THRESHOLD` | `5` | 1セラーで中古除外がこの件数を超えたらセラーごとスキップ（デフォルト5件→6件目でスキップ）。`0` で無効化 |

---

## 5. 除外判定の優先順位

商品一覧取得時（`_parse_item_card()`）と詳細取得後のGemini判定で、以下の順に除外が適用されます。先に適用されたルールで除外が確定した商品は後続の判定をスキップします。

```
① タイトルキーワード除外（config.EXCLUDE_TITLE_KEYWORDS）
   │  一覧ページの商品タイトルに除外キーワードが含まれていればNG
   │  例：チケット、食品、3M、危険物 など
   │
   ▼ 通過
② メーカー名除外（config.EXCLUDE_MAKER_KEYWORDS）
   │  タイトル先頭1〜2トークンが既知メーカー名であればNG
   │  ただし AUTOMOTIVE_KEYWORDS に該当する商品はバイパス（車種専用品は合法）
   │  例：HITACHI、Sony、Panasonic など
   │
   ▼ 通過
③ トレーディングカード判定フラグ付与（config.TRADING_CARD_KEYWORDS）
   │  ポケカ・遊戯王等のキーワードがあれば needs_card_check フラグをセット
   │  → Gemini判定でカード本体か周辺グッズかを識別
   │
   ▼
④ Geminiテキスト判定（gemini_client.classify_item_text()）
   │  タイトルテキストのみでGeminiに問い合わせ
   │  excluded / ok / needs_vision の3値を返す
   │  needs_vision の場合は次のステップへ
   │
   ▼ needs_vision または グループサイズ ≥ VISION_MIN_GROUP_SIZE
⑤ Gemini Vision判定（gemini_client.classify_item_full()）
      グループ代表画像（複数枚）＋タイトルでGeminiに問い合わせ
      excluded → NG / ok → 候補として維持 / review → 要確認フラグ
```

**補足**:
- `GEMINI_ENABLED=false` の場合は④⑤をスキップ。pHashグループ化まで実行し、グループサイズによるステータス昇格のみ行います
- `needs_review=True` になった商品はグリッドに「要確認」バッジが表示されますが除外はされません。ユーザーが手動でOK/NGを判断します

**AUTOMOTIVE_KEYWORDS によるバイパスの技術的詳細**:

`_parse_item_card()` 内で②のメーカー名チェック（Tier 1除外）を行う前に、商品タイトルが `config.AUTOMOTIVE_KEYWORDS` のいずれかのキーワードに一致するかを検査します。一致した場合はメーカー名チェックをスキップ（バイパス）し、次の判定ステップへ進みます。

- **管理場所**: `config.py` 内の `AUTOMOTIVE_KEYWORDS` リスト（例：`["トヨタ", "ホンダ", "ヤマハ", "カー用品", "バイク用品", ...]`）
- **追加方法**: `config.py` の `AUTOMOTIVE_KEYWORDS` に直接追記するか、`.env` の `EXCLUDE_MAKER_KEYWORDS` の除外対象から該当車種名を外す形で調整します
- **意図**: カー用品・バイク用品はメーカー互換品・汎用品が多く、タイトルにブランド名が含まれていても仕入れ対象になりうるため、メーカー名除外の例外として設けています

---

## 6. セッションフォルダ命名規則

### 新命名規則（現行）

| STEP | パターン | 例 |
|---|---|---|
| STEP 1 | `S1_YYYYMMDD_NN_keyword` | `S1_20260506_01_バフ` |
| STEP 2 | `S2_YYYYMMDD_NN` | `S2_20260506_01` |
| STEP 3 | `S3_YYYYMMDD_NN` | `S3_20260506_01` |

`NN` は同日・同ステップ内の通番（01, 02, ...）。`keyword` はOS禁止文字を除いた最大15文字。

### 旧命名規則（後方互換）

| STEP | パターン | 例 |
|---|---|---|
| STEP 1 | `keyword_YYYYMMDD_HHMMSS` | `バフ_20260101_143022` |
| STEP 2 | `seller_analysis_YYYYMMDD_HHMMSS` | `seller_analysis_20260101_143022` |
| STEP 3 | `master_analysis_YYYYMMDD_HHMMSS` | `master_analysis_20260101_143022` |

旧フォルダは `app.py` の `_parse_session_info()` / `app.js` の `parseSessionName()` の両方で読み込み可能です。新規作成は常に新命名規則を使います。

---

## 7. よく変更する設定とその場所

### スクレイピング速度を調整したい

`.env` で `MIN_DELAY` / `MAX_DELAY` を変更します。デフォルト3〜5秒。短くするとサーバー負荷が上がります。

### 価格帯を変えたい

`.env` で `MIN_PRICE` / `MAX_PRICE` を変更します（単位：円）。

### 候補グループの条件を緩くしたい

`.env` で `MIN_GROUP_SIZE` を下げます（例：`3`）。`MIN_NEXT_CANDIDATE_SIZE` も合わせて調整します。

### マスターリストへの追加条件を変えたい

`.env` で `MASTER_SELLER_MIN_GROUP_SIZE` を変更します。デフォルト `2`（2件以上のグループを持つセラーのみ追加）。

### 除外キーワードを追加したい

- タイトルキーワード：`.env` の `EXCLUDE_TITLE_KEYWORDS` にカンマ区切りで追記（例：`EXCLUDE_TITLE_KEYWORDS=新製品,limited`）
- メーカー名：`.env` の `EXCLUDE_MAKER_KEYWORDS` に追記
- 根本的に追加したい場合は `config.py` の `_EXCLUDE_KEYWORDS_DEFAULT` / `_EXCLUDE_MAKERS_DEFAULT` リストに直接追記

### AucFanのHTML構造が変わったとき

`config.py` の `SELECTORS` 辞書を更新します。各セレクターはリスト形式で、先頭から順に試行されます。新しいセレクターをリストの先頭に追加するのが安全です。

### Geminiモデルを変えたい

`.env` で `GEMINI_MODEL_VISION` / `GEMINI_MODEL_TEXT` を変更します（例：`gemini-1.5-pro`）。

### Gemini判定プロンプトを調整したい

`prompts.yaml` を編集します。このファイルはGit管理下にあり、プロンプト変更の履歴を追跡できます。`gemini_client.py` 内の `_DEFAULT_PROMPTS` はフォールバック用で通常は変更不要です。

### Flaskポートを変えたい（競合時）

`.env` で `FLASK_PORT` を変更します（デフォルト `5001`）。

### iPhoneからのアクセスが繋がらない

`FLASK_HOST=0.0.0.0`（デフォルト）になっていることを確認します。MacのファイアウォールでFlaskのポートが許可されているかも確認してください。

---

## 8. 開発時の注意事項

**構文チェック（変更後に実行）**：
```bash
# Python
python3 -m py_compile app.py data_manager.py scraper.py seller_analyzer.py gemini_client.py sellers_master.py config.py

# JavaScript
node --check static/app.js
```

**スレッドセーフ**: `app.py` のグローバル状態（`_seller_state`, `_master_state`）は `_seller_lock` / `_master_lock` で保護して読み書きしてください。`DataManager` と `SellersMaster` は内部でロックを持っているので外部からロック不要です。

**SSEストリーム**: 進捗はSSE（Server-Sent Events）でブラウザに送信されます。`/api/progress`, `/api/seller/progress`, `/api/master/progress` がそれぞれジェネレーター関数を返す Flask `Response` です。接続が切れても次のポーリングで再接続されます。

**フロントエンドのステップ切り替え**: `app.js` の `switchStep(step)` が各パネルの表示/非表示を管理します。`step` は `'1'`, `'2'`, `'3'`, `'master'` の4値です。切り替え時に `localStorage.setItem('activeStep', step)` で現在タブを保存し、ページリロード後も `DOMContentLoaded` で復元します（iPhone Safariでリロードしてもタブが戻らない）。

**セッション読み込み**: `loadSessionToGrid(sessionName)` が `/api/sessions/<name>/load` を呼び出し、`loadGroups()` でグリッドを更新し、`refreshCurrentSession()` で「📌 表示中:」バーを更新します。この3ステップのシーケンスが重要です。

---

### `app.js` — フロントエンドの主要関数

`static/app.js` はバニラJSで書かれたフロントエンドロジックです。以下は改修に関連する主要関数をまとめています。

**進捗・完了バナー制御**:

| 関数 | 説明 |
|---|---|
| `updateProgressUI(data)` | STEP 1のポーリングレスポンス（`scrape_status`）を受け取り、`data.processed_items` を読んで画面上のカウンターを更新する。`data.phase === 'done'` の場合に緑色の完了バナーを表示する |
| `fetchSellerStatus()` | STEP 2の進捗をポーリングして `seller_status.processed_items` からカウンターを更新し、完了時に完了バナーを表示する |
| `fetchMasterStatus()` | STEP 3の進捗をポーリングして `master_status.processed_items` からカウンターを更新し、完了時に完了バナーを表示する |

完了バナーは `<div class="scrape-complete-banner">✅ スクレイピング完了（N件処理）</div>` として動的に生成され、✕ボタンのクリックで `remove()` されます。

**ヘッダーステータス表示（`headerStatus` 要素）**：

アプリタイトル右に表示される状態インジケーター。STEP1はSSEストリームの `updateProgressUI()` が更新する。STEP2/3はSSEがSTEP1専用のため、`fetchSellerStatus()` / `fetchMasterStatus()` の末尾でそれぞれ直接更新する。ログイン待ち時は `login_required` ステータスに対して各ポーリング関数の先頭で `return` する前にヘッダーを更新する。対応ステータスラベル: `idle`=待機中 / `scraping_list`=一覧取得中 / `scraping_detail`=詳細取得中 / `grouping`=グループ化中 / `vision_check`=🤖 Vision判定中 / `login_required`=⚠️ ログイン待ち / `done`=完了 / `stopped`=停止済み / `error`=エラー。

**ログイン待ちバナーと「今すぐ確認して再開」ボタン**：

スクレイパーが `login_required` ステータスを発行すると `updateBanner()` が `type: 'login'`（琥珀色 `#78350f`・左黄ボーダー）でバナーを表示する。バナーには `showLoginBtn: true` 時のみ表示される「🔄 今すぐ確認して再開」ボタン（`id="bannerLoginCheckBtn"`）を内包する。このボタンが押されると `triggerLoginCheck()` が `/api/login_check` をPOSTし、Python側の `_login_check_event.set()` 経由で30秒待機ループを即時起動する。タブ移動・ページリロードは一切行わない。

**`sellerStatusBadge(status, usedCount)` 関数**:

セラーリストの各行に表示するステータスバッジHTMLを返します。対応ステータス：`pending`（待機中）/ `running`（処理中）/ `done`（✅ 完了）/ `error`（❌ エラー）/ `used_skip`（🚫 中古N件超でスキップ・オレンジ）。`used_skip` 時は第2引数 `usedCount`（セラー辞書の `used_count` フィールド）を受け取り、「🚫 中古7件超でスキップ」のように実際の件数をバッジに表示します。`used_count` は `on_progress` コールバックの `extra` 引数経由でセラー辞書に保存されます。ターミナルにも `🚫 中古セラースキップ: seller_id / 中古件数: N件（閾値: M件超でスキップ）` と枠線付きで出力されます。

**`exportGroupExcel(groupId, btn)` 関数**:

商品カードの **📗 Excel** ボタンから呼び出されます。指定グループ1件分のExcelリサーチシートを生成し、Google Drive の `AucFanToolData/リサーチ結果/` に保存します。

- **引数**: `groupId: string` — グループID（`renderGroupCard()` から渡される）、`btn: HTMLElement` — 押されたボタン要素（処理中の disabled 制御用）
- **動作**: ボタンを ⏳ に変えて `POST /api/export/excel/<groupId>` を呼び出す。成功時は「📗 Excel保存: ファイル名」のトーストを表示。失敗時は「❌ Excel保存失敗」のエラートーストを表示。finallyブロックでボタンを元の「📗 Excel」に戻す
- **ボタンの配置**: `renderGroupCard()` 内で ❌ NG ボタンの右隣に `<button class="btn btn-success btn-sm" onclick="exportGroupExcel(...)">📗 Excel</button>` として挿入

**`validateNotHtmlFile(file)` ヘルパー関数**:

CSV読み込み系のファイル選択イベントで呼び出されるバリデーション関数です。

- **引数**: `file: File` — `<input type="file">` の選択ファイルオブジェクト
- **戻り値**: `boolean` — `true` の場合は正常（HTMLでない）、`false` の場合は不正なHTMLファイル
- **動作**: ファイル名が `_iPhone_iPad用.html` で終わる場合は「このファイルはiPhone/iPad閲覧用のHTMLです」、`_Mac用.html` で終わる場合は「このファイルはMac閲覧用のHTMLです」という赤いトーストメッセージを表示してアップロードを中断します
- **適用箇所**: STEP 2・STEP 3のCSV読み込みボタン、マスターリストの📂 CSV読み込みボタンのすべての `change` イベントハンドラーから呼び出されます

---

### `excel_exporter.py` — Excelリサーチシート生成

商品カードの📗ボタンから呼び出されるExcelエクスポートモジュールです。テンプレート方式を採用しており、`リサーチ_テンプレート.xlsx` を `openpyxl.load_workbook()` で読み込み、値だけを書き込んで返します。書式（色・フォント・罫線など）の変更はテンプレートファイルをExcelで直接編集するだけでコードは一切変更不要です。

**定数**：

| 定数 | 値 | 説明 |
|---|---|---|
| `TEMPLATE_PATH` | `Path(__file__).parent / "リサーチ_テンプレート.xlsx"` | テンプレートの場所（aucfan_tool/ 直下） |
| `DATA_ROW` | `6` | データを書き込む行番号（Row1〜5はヘッダー） |
| `THUMB_MAX_W / H` | `110 / 90` | サムネール画像のリサイズ上限（px） |

**主要関数**：

| 関数 | 説明 |
|---|---|
| `sanitize_filename(title, max_len=60)` | ファイル名に使えない文字（`\/:*?"<>|`）を除去して最大60文字に切り詰める |
| `_make_thumb(src_path, tmp_dir)` | PILで画像をリサイズ（LANCZOS）してJPEGに変換し、tmp_dir に保存したパスを返す。失敗時は `None` |
| `_get_group(dm, group_id, session_name="")` | `DataManager.get_all_items()` からグループデータを収集してdictで返す。`title`・`group_size`・`min_total`・`sellers`（最大3件）・`url`・`thumb_path` を含む。`thumbnail_local` のパスが存在しない場合（reader Mac など）は `config.LOCAL_IMAGE_CACHE_DIR / session_name / images / filename` をフォールバックとして探す |
| `_fill_sheet(ws, group, session_name, row)` | ワークシートの指定行にデータを書き込む（書式はテンプレートのまま維持） |
| `generate_excel_single(dm, group_id, embed_images=True)` | グループ1件のExcelを生成して `(bytes, filename)` を返す。失敗時は `None` |
| `generate_excel_single_with_session(dm, group_id, session_name, embed_images=True)` | `session_name` を明示的に渡すバージョン。`app.py` から呼ばれる |

**`_fill_sheet()` が書き込むセル**：

| セル | 内容 |
|---|---|
| A1 | タイトルバー（`Aucfan リサーチシート  ―  セッション名`） |
| F2（B2:L2マージ） | セッション名 + エクスポート日付 |
| B2, D2 | COUNTA / COUNTIF サマリー数式（DATA_ROWに合わせて調整） |
| row 列A | 連番（1） |
| row 列C | エクスポート日時 |
| row 列D | 代表キーワード（商品タイトル） |
| row 列E | 件数（group_size、直近30日の落札数） |
| row 列F | 4件以上フラグ（`=IF(E{row}>=4,"✓","✗")` 数式） |
| row 列G | 最安値（min_total、0の場合は空白） |
| row 列H/I/J | セラーID①②③ |
| row 列K | 検索URL |
| row 列B（画像） | サムネール画像（embed_images=True かつ thumb_path が存在する場合） |

**テンプレートの再生成**：

`build_template.py` を `python3 build_template.py` で実行すると `リサーチ_テンプレート.xlsx` を新規作成します。スタイル定数（`HDR_BG`, `SUB_BG` 等）やカラム定義（`COLUMNS` リスト）をこのスクリプト内で変更して再実行することで、書式をコードから制御することもできます。通常はExcelで直接テンプレートを編集する方が簡単です。

**画像埋め込みの実装上の注意点**：

openpyxl は `XLImage(path)` の時点ではパスを文字列として記憶するだけで、実際に画像ファイルを読み込むのは `wb.save()` のタイミングです。そのため `wb.save()` は必ず `tempfile.mkdtemp()` で作成した一時ディレクトリを削除（`shutil.rmtree`）する **前** に呼ぶ必要があります。`finally` ブロックで先に削除すると `FileNotFoundError` が発生します。

```python
# ✅ 正しい順序（wb.save → shutil.rmtree）
try:
    ...画像埋め込み処理...
    wb.save(buf)   # ← tmp_dir が存在するうちに保存
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

# ❌ 誤った順序（shutil.rmtree → wb.save）
finally:
    shutil.rmtree(tmp_dir)
wb.save(buf)  # ← FileNotFoundError
```

**reader Mac での画像パス解決（`_get_group` のフォールバック）**：

`thumbnail_local` に記録されているのはスクレイピング時（scraper Mac）のローカルパスです。reader Mac では該当パスが存在しないため、ファイル名だけ取り出して `config.LOCAL_IMAGE_CACHE_DIR / session_name / images / filename` を探します。reader Mac では `LOCAL_IMAGE_CACHE_DIR` が GDrive ミラーリング済みフォルダを指すため、GDrive に画像がアップロード済みかつミラーリング同期済みであれば画像入り Excel を出力できます。

---

### `switch_role.sh` — 役割切り替えスクリプト

`.env` の `SITE_ROLE` と `GDRIVE_UPLOAD_ENABLED` をワンコマンドで書き換えます。`sed -i ''` で既存行を上書き（コメントアウト行も含む）し、キーが存在しない場合は末尾に追記します。

```bash
bash switch_role.sh scraper     # SITE_ROLE=scraper / GDRIVE_UPLOAD_ENABLED=true
bash switch_role.sh reader      # SITE_ROLE=reader  / GDRIVE_UPLOAD_ENABLED=false
bash switch_role.sh standalone  # SITE_ROLE=scraper / GDRIVE_UPLOAD_ENABLED=false
                                # + OUTPUT_BASE_DIR=リサーチ結果
                                # + SELLERS_MASTER_PATH=data/sellers_master.json
```

standalone モードでは `OUTPUT_BASE_DIR` をローカルパス（`リサーチ結果`）に固定し、GDrive を完全に使わない構成にします。scraper / reader モードでは `OUTPUT_BASE_DIR` をコメントアウトして `config.py` の自動検出に任せます。

**.env が存在しない場合**は `.env.example` から自動コピーします。実行後は `bash start.sh` でアプリを再起動してください。

---

### `amazon_scraper.py` — Amazon商品ページデータ取得

Chrome のリモートデバッグポート（9222）に接続し、`amazon.co.jp` の商品ページから BeautifulSoup で商品情報を抽出します。

**主な関数**：

| 関数 | 説明 |
|---|---|
| `_connect_chrome()` | ポート9222に接続して driver を返す。`driver.quit()` は呼ばない（Chromeを閉じないため） |
| `_expand_and_parse(driver, url)` | 折りたたみセクション展開→スクレイプ→dict返却。全機能の共通コア |
| `fetch_amazon_product()` | 現在開いているAmazonタブから取得 |
| `fetch_amazon_from_url(url)` | URL指定。新規タブで開いてスクレイプし、タブを閉じて元タブに戻る |
| `resolve_short_url(url)` | amzn.asia等の短縮URLをHTTPリダイレクトで解決 |

**折りたたみ展開**：`_expand_and_parse()` は BeautifulSoup でパースする前に、Selenium で以下のボタンをクリックする：
- `#productDetails_expanderSectionShowAll`
- `.a-expander-prompt`
- `[data-action='a-expander-toggle']`

**仕様テーブル取得（4パターン対応）**：
1. `#productOverview_feature_div tr` — ページ上部の「商品情報」テーブル
2. `#productDetails_techSpec_section_1 tr` 等 — 「技術仕様」テーブル
3. `#detailBullets_feature_div ul li` — dl/dt/dd形式（新デザイン）
4. `#technicalSpecifications_section_1 tr` — その他形式

**全画像URL取得**：
- `#altImages li.item img` のサムネイルURLを `_SL1000_` 高解像度に変換
- JavaScriptで `data-a-dynamic-image` を取得して最高解像度URLを選択
- 重複除去済みのリストを `image_urls: [...]` として返す

**評価抽出**：「5つ星のうち4.1」テキストから `のうち` の後の数値を正規表現で抽出（`5` を誤取得しないよう対策済み）

**戻り値** (`_expand_and_parse()` の返す dict)：

```python
{
    "success": True,
    "url": "https://...",
    "asin": "B0XXXXX",
    "title": "...",
    "price": "￥2,280",
    "image_url": "https://...メイン画像...",
    "image_urls": ["https://...1枚目...", "https://...2枚目...", ...],
    "bullets": ["特徴1", "特徴2", ...],
    "description": "商品説明テキスト",
    "specs": {"取り付けタイプ": "ドアマウント", "サイズ": "220mm x 220mm", ...},
    "rating": "4.1",
    "review_count": "(514)",
    "has_aplus": True,
}
```

**APIエンドポイント（app.py）**：

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/api/amazon/fetch` | POST | 現在のChromeタブからデータ取得・group_id紐付け保存 |
| `/api/amazon/data/<group_id>` | GET | 指定group_idの保存済みAmazonデータを返す |
| `/api/research/amazon/append` | POST | 現在タブ取得→Excel追記（/researchページ用） |
| `/api/research/amazon/fetch-url-append` | POST | URL指定取得→Excel追記（短縮URL対応） |
| `/api/research/amazon/status` | GET | Amazon取得中ステータスのポーリング（`_research_fetch_status` を返す） |
| `/api/research/amazon/open-calculator` | POST | FBA料金シミュレータにASIN自動入力（Shadow DOM対応） |

---

### `scraper_1688.py` — 1688商品ページデータ取得

`amazon_scraper.py` と同じ Chrome port 9222 接続方式で 1688.com の商品ページをスクレイピングする。
（旧ファイル名 `1688_scraper.py` は Python がインポートできないため `scraper_1688.py` にリネーム済み）

**主な関数**：

| 関数 | 説明 |
|---|---|
| `_translate_zh_to_ja(text)` | 中国語→日本語翻訳。`deep_translator.GoogleTranslator` を使用。失敗時は空文字を返す（スクレイピング継続） |
| `_connect_chrome()` | ポート9222に接続して driver を返す（amazon_scraper と同じ） |
| `_parse_price_from_text(text)` | "预估到手单価" を優先取得。なければ ¥数値の最小値を返す |
| `_parse_moq_from_text(text)` | "20套起批" → `(20, "套")` にパース |
| `_parse_variants_from_body(body_text)` | body テキストのバリアントセクションから SKU 一覧を抽出。`ENTRY_HEADERS`/`STOP_HEADERS` で区分し套餐等の誤取込を防ぐ |
| `_parse_shop_info(driver)` | ショップ名・URL・評価（店铺服务分）・回頭率（店铺回头率）を取得。**サブドメイン方式** |
| `fetch_1688_from_url(url)` | メイン関数。新規タブで URL を開いてスクレイピングし、タブを閉じて戻る |

**バリアントセクション判定（ENTRY_HEADERS / STOP_HEADERS）**：

```python
ENTRY_HEADERS = {'规格', '尺寸', '颜色', '型号', '款式', '规格型号', '包装规格'}
STOP_HEADERS  = {'套餐', '数量', '颜色分类'}
# ENTRY_HEADERS が来たらバリアント行収集開始
# ループ中に他のヘッダー（ALL_HEADERS = ENTRY | STOP）が現れたら収集終了
# → 套餐（セット商品）がバリアントに混入しない
```

**ショップURL検出（`_is_shop_subdomain_url()`）**：

```python
def _is_shop_subdomain_url(u: str) -> bool:
    m = re.match(r'https?://([^./]+)\.1688\.com', u)
    if not m: return False
    sub = m.group(1).lower()
    NON_SHOP = {'www', 's', 'detail', 'login', 'account', 'message',
                'trade', 'm', 'wap', 'crm', 'buyer', ...}
    return sub not in NON_SHOP
```

- JS で全 `<a>` タグのhrefを収集し、サブドメインが非システム系（ショップ名）であれば採用
- ポジティブ検出方式のため `/page/offerlist.htm` 等を含むショップURLも正しく取得できる
- 旧実装は `/page/offerlist` をブロックしていたため、ショップURLが取れないバグがあった

**戻り値** (`fetch_1688_from_url()`)：

```python
{
    "success": True,
    "title": "商品名（中国語）",
    "title_ja": "商品名（日本語）",     # deep_translator で自動翻訳
    "shop_name": "ショップ名",
    "shop_url": "https://winport.1688.com",  # サブドメイン形式
    "shop_rating": "4.0分",
    "shop_repeat_rate": "47%",
    "shop_years": "9年",
    "min_price": 17.0,          # 最低単価（元）
    "moq": 20,                  # 最小発注数
    "moq_unit": "套",           # 単位
    "variants": [               # SKU一覧
        {"name": "小方镜", "price": 13.5, "stock": 199, "name_ja": "小型角ミラー"},
        {"name": "大方镜", "price": 30.0, "stock": 37,  "name_ja": "大型角ミラー"},
    ],
    "image_urls": ["https://cbu01.alicdn.com/..."],
    "attributes": {"材质": "不锈钢", ...},
    "url": "https://detail.1688.com/offer/...",
}
```

バリアントなし商品は `variants=[{"name":"デフォルト","price":X,"stock":Y,"name_ja":""}]` として返す。

**APIエンドポイント（app.py）**：

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/api/research/1688/fetch-url-append` | POST | URL指定取得→Excel追記（Sheet4/5 + 画像保存） |
| `/api/research/1688/status` | GET | 1688取得中ステータスのポーリング（`_research_1688_fetch_status` を返す） |

---

### `excel_append.py` — Excelへの追記モジュール（/researchページ用）

`app.py` の `/research` エンドポイントから呼び出される追記専用モジュール。

**主な関数**：

| 関数 | 説明 |
|---|---|
| `download_image(url, save_dir, name)` | メイン画像1枚をローカル保存 |
| `download_all_images(image_urls, save_dir, key)` | 全画像を `save_dir/{key}/01.jpg...` に保存 |
| `ensure_product_folders(excel_path)` | Excelと同フォルダに `amazon/` `1688/` を作成 |
| `get_excel_info(excel_path)` | シート名・Amazon件数・タイトル等を返す |
| `append_amazon(excel_path, data)` | Sheet2（②Amazonライバル）とSheet3（③Amazonテキスト）に追記 |
| `append_1688(excel_path, data)` | Sheet4（④1688仕入れ）とSheet5（⑤1688テキスト）に追記 |

**Sheet2 追記ロジック**：4行目以降で最初の空行を探して追記。画像は PIL でリサイズ後に `openpyxl.drawing.image.Image` で列I（9列目）に埋め込み。失敗時はURLをセルに書き込む。

**Sheet3 追記ロジック**：セパレーター行（緑背景・ASIN+タイトル）の後に6行（タイトル・価格・商品の特徴・商品説明・仕様・詳細）を追記。`cur_max + 2` 行目から開始することで複数ライバルが縦に並ぶ。

**Sheet4 追記ロジック（`append_1688`）**：バリアントを1行ずつ追記（19列構成）。

| 列 | 内容 | 書き込み値 |
|---|---|---|
| A(1) | 仕入れ選択 | 空（手入力用・薄黄背景） |
| B(2) | ショップ名 | `shop_name` |
| C(3) | ショップURL | `shop_url`（ハイパーリンクも設定） |
| D(4) | 信頼度 | 評価/回頭率 |
| E(5) | 入驻年数 | `shop_years` |
| F(6) | 商品名（中国語） | `title` |
| G(7) | 商品名（日本語） | `title_ja`（自動翻訳済み） |
| H(8) | バリアント（中国語） | `v["name"]` |
| I(9) | バリアント（日本語） | `v["name_ja"]`（自動翻訳済み） |
| J(10) | 在庫数 | `v["stock"]` |
| K(11) | 単価(CNY) | `v["price"]` |
| L(12) | 係数 | `rate`（`CNY_TO_JPY_RATE`、デフォルト35） |
| M(13) | MOQ | `moq`（常に書き込み、未指定=1） |
| N(14) | 仕入総額(CNY) | `=K{r}*M{r}` |
| O(15) | 仕入総額(JPY) | `=K{r}*M{r}*L{r}` |
| P(16) | 原価/個(JPY) | `=K{r}*L{r}` |
| Q(17) | 利益(JPY) | `=IFERROR(Sheet1!B12-Sheet1!B13-P{r},"")` |
| R(18) | 利益率 | `=IFERROR(TEXT(Q{r}/Sheet1!B12,"0.0%"),"")` |
| S(19) | 判定 | `=IF(AND(Q>=450, R>=25%), "◎","×")` |

- 空行検出は K列（単価）が `None` の行を探す
- フォーマットチェックは row 2（ヘッダー行）の列数が 18 以上かどうかで判定

**Sheet5 追記ロジック（`append_1688`）**：セパレーター行（黒緑背景）＋8行（商品名/ショップ名/ショップURL/最低単価/MOQ/バリアント一覧/商品属性）を追記。

**画像保存先**：Amazon: `Excelと同フォルダ/amazon/{ASIN}/01.jpg...`、1688: `Excelと同フォルダ/1688/{shop_key}/01.jpg...`

---

## 9. Excelリサーチシート — 現在の実装

### `excel_exporter.py` — 5シート構成Excel生成（完成済み）

`generate_excel_single_with_session(dm, group_id, session_name)` でAucFanデータをSheet1に書き込み、Sheet2〜5はヘッダーのみ（追記待ち）の5シートExcelを生成して bytes で返す。

**保存先フォルダ構成**（`app.py` の `/api/export/excel/<group_id>` で制御）：

```
OUTPUT_BASE_DIR/
  商品名/                       ← 自動作成
    商品名_リサーチ.xlsx
    amazon/                     ← 自動作成
    1688/                       ← 自動作成
```

**5シート構成**：

| シート | 名称 | 内容 |
|---|---|---|
| Sheet1 | ①概要 | AucFanデータ・手入力2セル（販売価格・FBA手数料）・自動計算 |
| Sheet2 | ②Amazonライバル | `excel_append.append_amazon()` が追記。列: ASIN/タイトル/価格/評価/レビュー数/A+/URL（実）/入力URL/画像 |
| Sheet3 | ③Amazonテキスト | 同上。縦並びスペック文 |
| Sheet4 | ④1688仕入れ | `append_1688()` でバリアント1行ずつ追記 |
| Sheet5 | ⑤1688テキスト | `append_1688()` でセパレーター＋8行追記 |

**計算ロジック（Sheet4 確定・19列）**：
- 係数(L) = `CNY_TO_JPY_RATE`（.envで設定、デフォルト35。送料・関税・代行手数料込み）
- 仕入総額(CNY)(N) = 単価(K) × MOQ(M)
- 仕入総額(JPY)(O) = 単価(K) × MOQ(M) × 係数(L)
- 原価/個(JPY)(P) = 単価(K) × 係数(L)
- 利益(JPY)(Q) = Sheet1!B12（販売価格）− Sheet1!B13（FBA手数料）− 原価/個(P)
- 利益率(R) = 利益(Q) ÷ 販売価格(Sheet1!B12)
- 判定(S) = 利益率 ≥ 25% かつ 利益 ≥ 450円 → ◎ / それ以外 ×

---

## 10. /research ページ — リサーチ追記ツール

`app.py` の `_RESEARCH_HTML` 変数にインライン文字列で定義された Flask ルート `/research` のページ。

**3セクション構成**：
1. **① Excelファイル選択** — `OUTPUT_BASE_DIR` を再帰スキャン（旧フラット形式・新サブフォルダ形式両対応）。クリックで選択、Amazon件数バッジを表示、ダウンロードボタンあり
2. **② Amazon URL取得・追記** — URL貼り付け → `fetch-url-append` → 成功後に「💴 FBA料金シミュレータで開く」ボタン表示
3. **③ 1688** — 1688商品URLを貼り付けて「取得→追記」。`scraper_1688.py` → `append_1688()` を経由してSheet4/5に書き込む

**Amazon取得中の進捗表示**：

グローバル変数 `_research_fetch_status` が処理の各ステップを管理する。

```python
# app.py グローバル
_research_fetch_status = {"running": False, "step": ""}

# fetch-url-append エンドポイント内で更新
_research_fetch_status = {"running": True, "step": "① URLを解析中..."}
# → "② ChromeでAmazonページを開いています..."
# → "③ Excelに書き込み中..."
# → finally: {"running": False, "step": ""}
```

フロントエンドは `fetchAmazonUrl()` 実行中に `/api/research/amazon/status` を1秒ごとにポーリングし、現在のステップと経過秒数を表示する。ボタンは処理完了まで無効化されるため2重送信も防止できる。

**FBA料金シミュレータ連携** (`/api/research/amazon/open-calculator`)：
- 既存の `revcal` タブを再利用（ログインページは再利用しない）
- Seller Central の revcal ページは **KAT UI** フレームワーク製で `<kat-input>` 等のカスタム要素が Shadow DOM 内に `<input>` を持つため、通常の CSS セレクターでは入力欄が見つからない
- JS で Shadow Root を再帰的に辿る `findInput()` / `findButton()` 関数で対応（入力欄・送信ボタン両方）
- Selenium が既存のログイン済み Chrome セッションを使うため、手動ログイン後はそのまま使用可能

**`fetch_amazon_from_url()` のタブ管理**：

```
① 事前クリーンアップ（CDP方式）
  Target.getTargets で全タブを取得。amazon.co.jp かつ /dp/ /gp/product/ を含まない
  タブ（= AucFan側から開いた検索タブ）を Target.closeTarget で閉じる。
  → window_handles は現在ウィンドウのみだが CDP は全ウィンドウを対象にできる

② switch_to.new_window('tab') で確実にタブとして開く
  （window.open('') はポップアップウィンドウになる場合があり、
   その後 driver.close() でウィンドウごと閉じてしまうため変更）

③ スクレイピング後の後処理
  len(driver.window_handles) > 1 → driver.close() でタブだけ閉じる
  len(driver.window_handles) == 1 → 閉じずに localhost:5001/research へ移動
  ※ 最後の1タブを close() するとChromeウィンドウごと閉じてしまうため

④ localhost タブを探して前面に戻す（なければ original_handle に戻す）
  _is_app_tab() は "/research" AND (localhost|127.0.0.1|:5001) の両方を確認
```

**`_is_app_tab(url)` ヘルパー**：

```python
def _is_app_tab(url: str) -> bool:
    return "/research" in url and any(
        x in url for x in ("localhost", "127.0.0.1", ":5001")
    )
```

リサーチ追記ツールが別Chromeウィンドウで表示される場合でも、CDPで全ウィンドウを対象にして正しく `app_handle` を特定できる。
