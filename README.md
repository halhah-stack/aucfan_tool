# AucFan Tool

AucFanの落札データをスクレイピングし、仕入れ候補商品をリサーチするMacアプリ。

## ドキュメント

| 対象 | ドキュメント |
|---|---|
| **はじめての方はここから**（概念・モード選択・セットアップ） | [QUICKSTART.md](QUICKSTART.md) |
| 機能の詳細・各操作リファレンス（非エンジニア向け） | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| セットアップ・別Mac移植手順 | [SETUP.md](SETUP.md) |
| コード解説・設定変更（エンジニア向け） | [docs/CODE_GUIDE.md](docs/CODE_GUIDE.md) |

## 運用モード

| モード | 用途 | `.env` の設定 |
|---|---|---|
| ① scraper（十王Mac） | スクレイピング実行・GDriveへアップロード | `SITE_ROLE=scraper` / `GDRIVE_UPLOAD_ENABLED=true` |
| ② reader（守谷Mac） | GDriveミラーリングで閲覧のみ | `SITE_ROLE=reader` / `GDRIVE_UPLOAD_ENABLED=false` |
| ③ standalone（1台完結） | Google Driveなしで1台完結 | `SITE_ROLE=scraper` / `GDRIVE_UPLOAD_ENABLED=false` |

役割の切り替えは `switch_role.sh` でワンコマンドできます。

```bash
bash ~/Downloads/aucfan_tool/switch_role.sh scraper     # スクレイピング専用
bash ~/Downloads/aucfan_tool/switch_role.sh reader      # 閲覧専用
bash ~/Downloads/aucfan_tool/switch_role.sh standalone  # 1台完結（GDrive不要）
```

## 起動

```bash
bash ~/Downloads/aucfan_tool/start.sh
```

ブラウザで http://localhost:5001 を開く。

## Excel リサーチシート出力

商品カードの **📗 Excel** ボタンを押すと、その商品1件分のリサーチシートを  
`AucFanToolData/リサーチ結果/商品タイトル_リサーチ.xlsx` として保存します。  
scraper Mac・reader Mac どちらからでも出力できます（reader Mac は GDrive ミラーリング済みの場合）。

出力書式は **`リサーチ_テンプレート.xlsx`** を直接Excelで編集するだけで変更できます。  
コードは「どのセルに何を書くか」だけを担当しています。

テンプレートを作り直したいときは：
```bash
cd ~/Downloads/aucfan_tool
python3 build_template.py
```

## リサーチ追記ツール（/research）

商品カードの **📊 リサーチ追記ツールを開く** ボタン、または `http://localhost:5001/research` から開きます。

```
① Amazon URL を貼り付けてライバル情報を追記（Sheet2）
② 1688 URL を貼り付けて仕入れ先を追記（Sheet4）
③ 「🚀 SP-API で取得・転記」ボタンで利益計算
   → 価格・FBA手数料を自動取得 → 1688原価（単価×35）込みで利益計算
   → ◎ GO（緑）/ × 要検討（赤）をその場で表示
```

① と ② は **順番不問**。SP-API 先でも 1688 先でも利益計算が出ます。

**設定値（`.env` で変更可能）**

| 設定 | デフォルト | 意味 |
|---|---|---|
| `CNY_TO_JPY_RATE` | `35` | 1688係数（元→円） |
| `PROFIT_RATE_THRESHOLD` | `25` | ◎判定の利益率（%） |
| `PROFIT_YEN_THRESHOLD` | `450` | ◎判定の利益額（円） |

## 除外ルールのメンテナンス

除外キーワード・メーカー名・カスタムルールはすべて **`rules.yaml`** で一元管理しています。

```bash
# rules.yaml を編集してルールを追加・変更
nano rules.yaml   # または好みのエディタで開く

# 変更を反映（再起動）
bash start.sh
```

アプリのNGボタンでGemini分析パネルを使うと、除外キーワード候補が提案されます。提案されたキーワードを `rules.yaml` に追記してください。詳細は [docs/USER_GUIDE.md §10](docs/USER_GUIDE.md) を参照。

## 初回セットアップ

```bash
cd ~/Downloads/aucfan_tool
cp .env.example .env   # テンプレートをコピー
nano .env              # モードに応じて編集
pip install -r requirements.txt
bash start.sh
```

詳細は [SETUP.md](SETUP.md) を参照してください。
