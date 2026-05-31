# HANDOVER — aucfan_tool 引き継ぎ書
更新日: 2026-05-31（午前）

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

~/Downloads/aucfan_tool/
  img_cache/              ← 十王Macのローカル画像キャッシュ
    セッション名/images/
```

---

## 今日（午前）完了した実装

| 内容 | ファイル |
|---|---|
| 1688 URL取得→バリアント選択→追記の2ステップUI | templates/research.html / routes/research.py |
| A列フラグ(1=対象/0=除外)のExcel自動入力 | excel_append.py |
| 追記済みバリアントのフラグをUIから変更・保存 | routes/research.py / templates/research.html |
| 1688重複チェック（同一商品の警告+スキップ/強制追記） | routes/research.py / templates/research.html |
| page_sourceフリーズ対策（45秒タイムアウト） | scraper.py |
| SP-APIでカテゴリー別成約料(ClosingFee)も取得 | sp_api_client.py |
| SP-API B13にreferral+fba+closing合計を書き込む修正 | routes/research.py |
| 在庫保管手数料の注記+FBAシミュレータリンク追加 | templates/research.html / excel_exporter.py |

---

## 利益計算の現状

**計算式（現状）：**
```
利益 = 販売価格(B12) - FBA手数料合計(B13) - 1688原価×35
```

**B13の内訳（SP-API取得後）：**
- 出荷費用（FBA配送）: 例 ¥425
- 販売手数料（紹介料）: 例 ¥477
- カテゴリー別成約料: 例 ¥0（一般商品）
- 合計: ¥902

**含まれていないもの：**
- 在庫保管手数料（商品サイズ・月によって異なる / SP-APIで取得不可）
  → UIとExcelにFBAシミュレータへの案内を追加済み

**販売価格のmin(AucFan, Amazon)対応：未着手**
- 現状B12は手動入力
- 要件: min(AucFan合計価格, Amazon価格)を自動で採用

---

## 守谷Macの残タスク

1. Google DriveをストリーミングからミラーリングへGDrive設定で変更
2. `.env`に追加: `SITE_ROLE=reader`
3. `git pull origin main`
4. `bash start.sh`

---

## 次回やること

1. **販売価格のmin(AucFan合計, Amazon価格)対応**
   - B12に`=MIN(AucFan合計セル, Amazon価格セル)`の数式を入れるか、コード側で計算
   - AucFan合計 = ①概要シートの既存セル参照
   - Amazon価格 = B12に手動入力 or SP-APIで取得済みの価格

2. **#VALUE!エラーの対処**
   - ①概要シートの利益計算式が④1688仕入れシートに1件もデータがない時に#VALUE!になる
   - `=IF(B16="","",(B12-B13-B16))`のB16が空だと下の式が連鎖エラー
   - IFERRORで囲むだけで対応可能

3. **テスト実施**
   - 1688 2ステップUI（取得→バリアント選択→追記）
   - バリアントフラグ変更UI
   - 重複チェック

---

## 未解決・保留

- 在庫保管手数料の扱い → 手動でFBAシミュレータ確認を促す方針で確定
- 守谷MacのGDrive設定変更 → 未実施

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
| sp_api_client.py | Amazon SP-API クライアント |
| pdf_exporter.py | PDF出力 |
| sellers_master.py | マスターセラーリスト管理 |
| build_template.py | Excelテンプレート生成 |

---

## git push 状況

以下のコミットが十王Macでまだpushされていない可能性あり：
```bash
rm ~/Downloads/aucfan_tool/.git/HEAD.lock
cd ~/Downloads/aucfan_tool
git add -A
git commit -m "午前の変更まとめ"
git push origin main
```
