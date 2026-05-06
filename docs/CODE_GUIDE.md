# コード解説書（エンジニア向け）

> 対象読者：このツールをメンテナンス・拡張するエンジニア  
> 最終更新：2026-05-06

---

## 1. プロジェクト構造

```
aucfan_tool/
├── app.py                  # Flaskアプリ本体・APIエンドポイント・バックグラウンドスレッド管理
├── config.py               # 全設定値（.envから読み込み）・CSSセレクター定義
├── scraper.py              # AucFan Seleniumスクレイパー（STEP 1 リスト取得 + 詳細取得）
├── seller_analyzer.py      # セラー分析スクレイパー（AucFanScraper継承、STEP 2）
├── data_manager.py         # セッションデータ管理・CSV/JSON保存・再開機能
├── image_processor.py      # 画像ダウンロード・pHash計算・グループ化
├── gemini_client.py        # Gemini Vision/Text API による除外判定
├── sellers_master.py       # マスターセラーリスト管理（data/sellers_master.json）
├── prompts.yaml            # Gemini用プロンプト定義（外部ファイル）
├── .env                    # 環境変数（Git管理外）
├── requirements.txt        # Python依存ライブラリ
│
├── templates/
│   └── index.html          # シングルページUI（Jinja2テンプレート）
│
├── static/
│   ├── app.js              # フロントエンドロジック（バニラJS）
│   └── style.css           # スタイルシート
│
├── data/
│   └── sellers_master.json # マスターセラーリスト（永続データ）
│
├── リサーチ結果/            # セッションフォルダ群（OUTPUT_BASE_DIR）
│   ├── S1_20260506_01_バフ/   # STEP 1セッション例
│   │   ├── progress.json
│   │   ├── items.json
│   │   ├── results.csv
│   │   └── images/
│   ├── S2_20260506_01/        # STEP 2セッション例
│   └── S3_20260506_01/        # STEP 3セッション例
│
└── docs/
    ├── USER_GUIDE.md        # ユーザー向けマニュアル
    └── CODE_GUIDE.md        # 本ドキュメント
```

---

## 2. 主要ファイルの解説

### `config.py` — 設定の集約点

すべての設定値は `config.py` に集中管理されており、`.env` ファイルから `python-dotenv` 経由で読み込まれます。ハードコードの変更は不要で、`.env` の書き換えだけで動作を調整できます。

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
| 出力先 | `OUTPUT_BASE_DIR=リサーチ結果` | セッションフォルダの親ディレクトリ |

**CSS セレクター (`SELECTORS` 辞書)**: AucFanのHTML構造が変わった際はここを更新します。`list`キー配下が一覧ページ用、`detail`キー配下が詳細ページ用で、それぞれ候補セレクターをリストで持ちます（先頭から順に試行します）。

---

### `data_manager.py` — データの中核

`DataManager` クラスはスクレイピング中のデータをメモリ上に保持し、定期的にディスクへ書き出します。1つのスクレイピングセッション＝1つの `DataManager` インスタンスに対応します。

**主要メソッド**：

| メソッド | 説明 |
|---|---|
| `add_item(item)` | 商品を追加。`item_id` を自動生成して返す |
| `update_item(item_id, updates)` | 商品データを部分更新 |
| `assign_group(item_ids, group_id)` | pHash結果のグループIDを商品に割り当て |
| `promote_candidates(min_group_size)` | グループサイズに応じてステータスを `candidate` / `next_candidate` に昇格 |
| `save_all()` | `progress.json` + `items.json` + `results.csv` を一括保存 |
| `load_previous_session()` | 前回の `progress.json` / `items.json` を読み込んで再開 |
| `get_stats()` | グループ単位のステータス集計を返す |

**セッションフォルダ作成**: `make_output_dir(keyword, step=1)` 関数（クラス外）がフォルダを作成し、`(out_dir: Path, session_id: str)` を返します。新命名規則は `S{step}_YYYYMMDD_NN[_keyword]/`。同日・同ステップの既存フォルダ数を走査して連番を決定します。

**スレッドセーフ**: すべてのデータ操作は内部の `threading.Lock` で保護されています。

---

### `scraper.py` — Seleniumスクレイパー（STEP 1）

`AucFanScraper` クラスがコアのスクレイピングロジックを担います。既存のChromeブラウザにリモートデバッグで接続し（`chrome://new-tab-page` を開いた状態で起動されたChrome）、AucFanの検索結果を順次取得します。

**主要な内部フロー**：

1. `connect()` — `selenium.webdriver.Remote` でポート9222に接続
2. `scrape_list_pages(keyword, url)` — 検索一覧を全ページ走査。各商品カードを `_parse_item_card()` で解析し、価格フィルタ・タイトルキーワード除外・メーカー名除外を適用
3. `_parse_item_card()` — 商品カードからタイトル・価格・セラーID・画像URL等を抽出。各種除外判定もここで実行
4. `run_phash_grouping()` — pHash計算後にハミング距離でグループ化し `assign_group()` を呼ぶ
5. `scrape_detail_pages()` — 候補商品の詳細ページを個別取得（STEP 1でのみ使用）
6. `_run_gemini_checks()` — グループサイズが `VISION_MIN_GROUP_SIZE` 以上のグループに対してGemini Vision判定を実行

`stop_event: threading.Event` が set されると各ループで検知して安全に停止します。

---

### `seller_analyzer.py` — セラー分析（STEP 2）

`AucFanScraper` を継承した `SellerAnalyzer` クラスです。複数のセラーURLを1セッションで順番にスクレイピングし、全商品をまとめてpHashグループ化します。

**特徴**：

- `scrape_detail=False`（デフォルト）のため詳細ページ取得はスキップ。一覧取得のサムネールだけでpHash判定を行います
- `skip_price_filter = True` に設定されるため価格フィルタは無効（セラーの全商品を対象とする）
- セラーごとに `on_seller_progress(index, status)` コールバックが呼ばれ、フロントエンドの進捗表示に使われます
- STEP 2の `min_group_size=1` で `promote_candidates()` を呼ぶため、全商品が `candidate` になります（単品でも表示対象）

---

### `image_processor.py` — 画像処理

`ImageProcessor` クラスが画像のダウンロードとpHash計算を担います。

- サムネール画像を `requests` でダウンロードし、セッションの `images/` ディレクトリに保存
- `imagehash.phash()` でPerceptual Hash（pHash）を64ビット文字列として計算
- `group_by_phash(items)` がハミング距離 ≤ `PHASH_THRESHOLD` の商品を同一グループとみなしてクラスタリング

---

### `gemini_client.py` — AI判定

`GeminiClient` クラスがGemini APIとのやり取りを管理します。プロンプトは `prompts.yaml` から読み込まれ、ファイルが存在しない場合はコード内のデフォルトプロンプトにフォールバックします。

**主要メソッド**：

| メソッド | 使用モデル | 用途 |
|---|---|---|
| `classify_item_text(title)` | `GEMINI_MODEL_TEXT` | タイトルテキストのみで除外判定 |
| `classify_item_vision(images, title)` | `GEMINI_MODEL_VISION` | 画像＋タイトルで同一商品・除外判定 |
| `classify_item_full(images, title)` | Vision | Vision単体で全判定（テキスト+Vision統合プロンプト） |

**レート制限**: `GEMINI_RPM_LIMIT=14` でリクエスト間隔を自動調整します（無料枠15RPMに対して安全マージンを設けています）。`GEMINI_ENABLED=false` または `GEMINI_API_KEY` 未設定の場合はAPI呼び出しをスキップしてpHashのみで動作します。

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
| `delete_seller(seller_id)` | 指定セラーを削除 |
| `clear_all()` | 全件削除 |

すべての操作で `threading.Lock` が使われており、スレッドセーフです。

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
| `/api/export/csv` | GET | 現在セッションをCSVエクスポート |
| `/api/export/html` | GET | 現在セッションをHTMLエクスポート |

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
  │ → まとめてpHashグループ化       │
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
| `GEMINI_MODEL_VISION` | `gemini-1.5-flash` | 画像判定に使用するGeminiモデル |
| `GEMINI_MODEL_TEXT` | `gemini-1.5-flash` | テキスト判定に使用するGeminiモデル |
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
| `OUTPUT_BASE_DIR` | `リサーチ結果` | セッションフォルダの保存先ディレクトリ名 |
| `EXCLUDE_TITLE_KEYWORDS` | `""` | 追加の除外タイトルキーワード（カンマ区切り） |
| `EXCLUDE_MAKER_KEYWORDS` | `""` | 追加の除外メーカー名（カンマ区切り） |
| `SELLER_SCRAPE_DETAIL` | `false` | `true` にするとSTEP 2でも詳細ページを取得する（非推奨・低速） |

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

**フロントエンドのステップ切り替え**: `app.js` の `switchStep(step)` が各パネルの表示/非表示を管理します。`step` は `'1'`, `'2'`, `'3'`, `'master'` の4値です。

**セッション読み込み**: `loadSessionToGrid(sessionName)` が `/api/sessions/<name>/load` を呼び出し、`loadGroups()` でグリッドを更新し、`refreshCurrentSession()` で「📌 表示中:」バーを更新します。この3ステップのシーケンスが重要です。
