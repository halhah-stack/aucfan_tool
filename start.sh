#!/bin/bash
# ─────────────────────────────────────────────
# start.sh - AucFan リサーチツール 一発起動
# 使い方: bash start.sh
# ─────────────────────────────────────────────

cd "$(dirname "$0")"

# 仮想環境を有効化
source .venv/bin/activate

# Chromeを完全終了（通常のChromeをそのまま使うため）
echo "🔴 Chromeを終了中..."
osascript -e 'quit app "Google Chrome"' 2>/dev/null
sleep 2

# Flaskをバックグラウンドで起動
echo "🚀 アプリを起動中..."
python app.py &
FLASK_PID=$!

# Flask が起動するまで待機（ポート5000が開くまでループ）
echo "⏳ Flask 起動待機中..."
for i in $(seq 1 20); do
  if curl -s http://localhost:5000 > /dev/null 2>&1; then
    echo "✅ Flask 起動確認"
    break
  fi
  sleep 1
done

# Flask確認後にChromeを起動（デバッグポート付き・専用プロファイル）
echo "🌐 Chromeを起動中..."
open -a "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.aucfan-chrome-profile"
sleep 3

echo ""
echo "✅ 起動完了！"
echo ""
echo "次の手順:"
echo "  1. Chromeで新しいタブを開く（⌘T）"
echo "  2. AucFanにログイン・検索条件を設定・1ページ目を表示"
echo "  3. localhost:5000のタブに戻ってスクレイピング開始"
echo ""
echo "Ctrl+C → Flaskのみ停止（Chromeはそのまま残ります）"
echo ""

# Ctrl+C 時にFlaskだけ終了するハンドラ
trap "echo ''; echo '🛑 Flask停止中...'; kill $FLASK_PID 2>/dev/null; exit 0" INT TERM

# Flaskプロセスが終了するまで待機
wait $FLASK_PID
