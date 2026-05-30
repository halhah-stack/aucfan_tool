# AucFan リサーチツール — はじめてガイド

> このファイルを読めば、初めてでも迷わずセットアップして使い始められます。  
> 詳細な機能説明は [docs/USER_GUIDE.md](docs/USER_GUIDE.md) を参照してください。

---

## このツールは何をするもの？

**AucFan**（ヤフオク等の落札データ集計サイト）から商品情報を自動収集し、  
「これ仕入れ候補になりそう」という商品グループを自動でピックアップするツールです。

手作業でやると数時間かかるリサーチを、ボタン1つで自動化します。

```
AucFan（ブラウザで表示中のページ）
        ↓ 自動スクレイピング
  落札データを大量収集
        ↓
  同じ商品をグループ化（画像の類似度で判定）
        ↓
  AIが食品・ブランド品・危険物などを自動除外
        ↓
  結果グリッドに表示 → Excelで書き出し
```

---

## まず「どの使い方にするか」を決める

このツールには3つの運用モードがあります。  
**最初は「スタンドアロン」が一番シンプルでおすすめです。**

| モード | 台数 | Google Drive | 向いている場面 |
|---|---|---|---|
| **スタンドアロン** | 1台 | 不要 | まず試したい・1台で完結させたい |
| **scraper + reader** | 2台 | 必要 | 十王Mac でスクレイピング、守谷Mac で閲覧・Excel出力 |

> **scraper / reader とは？**  
> scraper = 「データを集める役」、reader = 「集めたデータを見る役」という役割分担です。  
> 2台で使う場合、収集した画像データを Google Drive 経由で共有します。  
> 役割はいつでも `bash switch_role.sh [モード]` で切り替えられます。

---

## セットアップ手順

### A. スタンドアロン（1台完結）の場合

#### 1. 必要なものをインストールする

**ターミナルを開く**（Finder → アプリケーション → ユーティリティ → ターミナル）

```bash
# Homebrew（macOSのパッケージ管理ツール）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python
brew install python

# Git
brew install git
```

**Google Chrome** も必要です → https://www.google.com/chrome/

#### 2. ツールをダウンロードする

```bash
git clone https://github.com/halhah-stack/aucfan_tool.git ~/Downloads/aucfan_tool
cd ~/Downloads/aucfan_tool
pip install -r requirements.txt --break-system-packages
```

#### 3. 設定ファイルを作る

```bash
cd ~/Downloads/aucfan_tool
cp .env.example .env        # テンプレートをコピー
```

次に `.env` をテキストエディタで開いて以下の2箇所を編集します。

```dotenv
GEMINI_API_KEY=AIzaSy...    # ← Gemini APIキーを入力（下記で取得）
```

スタンドアロンモードへの切り替え（ワンコマンド）：

```bash
bash ~/Downloads/aucfan_tool/switch_role.sh standalone
```

> **Gemini APIキーの取得方法**  
> 1. https://aistudio.google.com/ を開いてGoogleアカウントでサインイン  
> 2. 左メニュー「Get API key」→「Create API key」  
> 3. 表示されたキー（`AIzaSy...`）をコピーして `.env` に貼り付け  
> ※ APIキーがなくてもpHashによるグループ化は動きます（AI判定なし）

#### 4. 起動して確認する

```bash
bash ~/Downloads/aucfan_tool/start.sh
```

ブラウザで `http://localhost:5001` が開けばセットアップ完了です。

---

### B. 2台運用（scraper + reader）の場合

**まずAの手順を両方のMacで完了させてください。**  
そのあと各Macで役割を設定します。

**スクレイピングするMac（scraper）で実行：**

```bash
bash ~/Downloads/aucfan_tool/switch_role.sh scraper
```

画面の指示に従って Google Drive アプリを「ストリーミング」モードに設定し、  
`credentials.json` を配置して初回認証を実行してください。

**閲覧するMac（reader）で実行：**

```bash
bash ~/Downloads/aucfan_tool/switch_role.sh reader
```

画面の指示に従って Google Drive アプリを「ミラーリング」モードに設定してください。

> **2台運用のメリット**  
> scraper Mac はスクレイピング専用なので Chrome を閉じずに動かせます。  
> reader Mac は Google Drive に同期されたデータをいつでも閲覧・Excel 出力できます。

---

## 毎日の使い方（基本フロー）

```
① bash start.sh でアプリを起動

② Chrome で AucFan を開いてログイン
   → 検索したいキーワードで検索し、1ページ目を表示

③ アプリのSTEP 1タブでスクレイピング開始
   → 完了するまで待つ（数分〜数十分）

④ 結果グリッドで商品を確認 → 仕入れ候補なら OK / 違えば NG

⑤ 気になる商品カードの📗 Excelボタンでリサーチシートを保存

⑥ 「📊 リサーチ追記ツールを開く」で /research ページへ
   → Amazon URL を貼り付けてライバル情報を追記
   → 1688 URL を貼り付けて仕入れ先を追記
   → 「🚀 SP-API で取得・転記」ボタンで利益計算
   → ◎ GO（緑）なら仕入れ確定 / × 要検討なら次の商品へ

⑦ 次のキーワードへ
```

---

## 3つのSTEPって何が違うの？

| STEP | やること | いつ使う |
|---|---|---|
| **STEP 1** キーワードリサーチ | キーワード検索 → 候補抽出 | 普段のリサーチ（メイン） |
| **STEP 2** セラーリサーチ | 特定セラーの全商品を収集 | 気になるセラーを深掘りするとき |
| **STEP 3** マスターリスト横断 | 蓄積したセラーIDをまとめてリサーチ | セラーが増えてきたら定期実行 |

**最初はSTEP 1だけ使えばOKです。**  
STEP 1を重ねていくとセラーIDが蓄積され、STEP 2→3 が活きてきます。

---

## 役割を切り替えたいとき

```bash
bash ~/Downloads/aucfan_tool/switch_role.sh scraper     # スクレイピング専用に
bash ~/Downloads/aucfan_tool/switch_role.sh reader      # 閲覧専用に
bash ~/Downloads/aucfan_tool/switch_role.sh standalone  # 1台完結に
```

切り替え後は `bash start.sh` でアプリを再起動してください。  
残りの手動作業（Google Drive アプリのモード変更など）はコマンド実行後に画面に表示されます。

---

## よくある「最初の疑問」

**Q. Google Drive は必ず使わないといけない？**  
A. いいえ。1台で完結させる「スタンドアロンモード」では Google Drive は不要です。

**Q. AucFan のアカウントは必要？**  
A. はい。AucFan のアカウント（無料）が必要です。スクレイピング前にブラウザでログインしてください。

**Q. Gemini APIキーがなくても動く？**  
A. 動きます。AI判定なしで、画像の類似度（pHash）だけでグループ化します。食品・ブランド品の自動除外はできなくなります。

**Q. スクレイピング中に別の作業はできる？**  
A. できます。Chrome とアプリのタブを残したまま他の作業をしていてOKです。

**Q. データはどこに保存される？**  
A. スタンドアロン → `~/Downloads/aucfan_tool/リサーチ結果/`  
　 scraper/reader → Google Drive の `AucFanToolData/リサーチ結果/`

---

## 詳細を調べたいとき

| 知りたいこと | 参照先 |
|---|---|
| 各機能の詳しい使い方 | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| 設定値の変更・別Macへの移植 | [SETUP.md](SETUP.md) |
| コードの仕組み・拡張方法 | [docs/CODE_GUIDE.md](docs/CODE_GUIDE.md) |

---

*最終更新: 2026年5月31日*
