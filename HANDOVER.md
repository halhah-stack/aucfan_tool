# HANDOVER — aucfan_tool 引き継ぎ書
更新日: 2026-05-31

---

## 2台のMac構成

| Mac | ホスト名 | SITE_ROLE | 画像保存先 |
|---|---|---|---|
| 十王Mac | shino@Juo-macmini | scraper（デフォルト） | ~/Downloads/aucfan_tool/img_cache/セッション名/images/ |
| 守谷Mac | — | reader（.envに追加） | GDriveミラーリングパスを直接参照 |

---

## フォルダ構成

```
GDrive/AucFanToolData/
  リサーチ結果/
    セッション名/          ← CSV・HTML・PDF
      images/             ← 画像（十王Macがコピー）
  リサーチシート/
    商品名/
      商品名_リサーチ.xlsx
      amazon/
      1688/
  sellers_master.json
```

```
~/Downloads/aucfan_tool/
  img_cache/              ← 十王Macのローカル画像キャッシュ
    セッション名/images/
```

---

## 完了した修正・実装（このセッション）

| 内容 | ファイル |
|---|---|
| STEP2安いバイクページ問題修正 | scraper.py / seller_analyzer.py |
| iPhone HTML export廃止 | app.py / static/app.js |
| SITE_ROLEシステム導入 | config.py / image_processor.py |
| GDriveフォルダ自動作成修正 | image_processor.py |
| config.py _GDRIVE_BASE定義順序バグ修正 | config.py |
| app.py GDriveパスハードコード修正 | app.py |
| pdf_exporter.py 画像パス修正 | pdf_exporter.py |
| セッション削除時にimg_cacheも同時削除 | app.py |
| .env の古いOUTPUT_BASE_DIR削除（十王Mac対応済み） | .env（手動） |
| 1688バリアント利益計算をA列フラグ(1=対象/0=除外)で制御 | routes/research.py / excel_exporter.py |

---

## 十王Macの現状

- `.env` の `OUTPUT_BASE_DIR` 削除済み → セッションは `AucFanToolData/リサーチ結果/` に保存
- Flask再起動が必要な場合: `bash start.sh`
- git push が必要なコミットあり（サンドボックスからpush不可のため）:
  ```bash
  cd ~/Downloads/aucfan_tool
  git push origin main
  ```

---

## 守谷Macの残タスク

1. Google DriveをストリーミングからミラーリングへGDrive設定で変更
2. `.env` に追加:
   ```
   SITE_ROLE=reader
   ```
3. コードを最新化:
   ```bash
   cd ~/Downloads/aucfan_tool
   git pull origin main
   ```
4. Flask起動: `bash start.sh`

---

## 次回やること（未着手）

### 利益計算の続き
- **販売価格を `min(AucFan合計, Amazon価格)` にする**
  - 現状: ①概要シートのB12固定値
  - 要件: AucFan価格（送料込み合計）とAmazon価格（FBA込み）の安い方を採用
  - 実装案: B12に `=MIN(AucFan合計セル, Amazon価格セル)` の数式を入れるか、コード側で計算

### 1688スクレイピングの確認
- `scraper_1688.py` は存在するが動作確認が必要
- URLを貼り付けて実行 → Excelの④1688仕入れシートに追記されるか検証

### Excel ④1688仕入れシート A列フラグ運用
- 新規作成したExcelから有効（既存ファイルはヘッダーが旧表記だが1を入力すれば動作する）
- A列に `1` を入力したバリアントだけ利益計算対象になる

---

## 主要ファイル一覧

| ファイル | 役割 |
|---|---|
| app.py | Flask メインアプリ |
| config.py | 全設定値 |
| scraper.py | AucFanスクレイピング |
| seller_analyzer.py | STEP2/3セラー分析 |
| image_processor.py | 画像DL・pHash・GDriveコピー |
| excel_exporter.py | AucFan→Excel生成（5シート） |
| excel_append.py | Amazon・1688データ追記 |
| scraper_1688.py | 1688スクレイピング |
| routes/research.py | リサーチUIルート・利益計算 |
| pdf_exporter.py | PDF出力 |
| sellers_master.py | マスターセラーリスト管理 |
| build_template.py | Excelテンプレート生成 |
