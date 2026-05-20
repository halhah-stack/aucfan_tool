# AucFan Tool

AucFanの落札データをスクレイピングし、仕入れ候補商品をリサーチするMacアプリ。

## ドキュメント

| 対象 | ドキュメント |
|---|---|
| 使い方・導入準備（非エンジニア向け） | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| セットアップ・移植手順 | [SETUP.md](SETUP.md) |
| コード解説・設定変更（エンジニア向け） | [docs/CODE_GUIDE.md](docs/CODE_GUIDE.md) |

## 運用モード

| モード | 用途 | `.env` の設定 |
|---|---|---|
| ① scraper（十王Mac） | スクレイピング実行・GDriveへアップロード | `SITE_ROLE=scraper` / `GDRIVE_UPLOAD_ENABLED=true` |
| ② reader（守谷Mac） | GDriveミラーリングで閲覧のみ | `SITE_ROLE=reader` / `GDRIVE_UPLOAD_ENABLED=false` |
| ③ standalone（1台完結） | Google Driveなしで1台完結 | `SITE_ROLE=scraper` / `GDRIVE_UPLOAD_ENABLED=false` |

どちらのMacも `.env` の2行を書き換えるだけで役割を入れ替えられます。

## 起動

```bash
bash ~/Downloads/aucfan_tool/start.sh
```

ブラウザで http://localhost:5001 を開く。

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
