#!/bin/bash
# ─────────────────────────────────────────────
# start.sh - AucFan リサーチツール 一発起動
# 使い方: bash start.sh
# ─────────────────────────────────────────────

cd "$(dirname "$0")"

# 仮想環境を有効化
source .venv/bin/activate

# .env からFlaskポートを読み込む（デフォルト5000）
FLASK_PORT=$(grep -E '^FLASK_PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo "5000")
FLASK_PORT=${FLASK_PORT:-5000}

# Chromeを完全終了（通常のChromeをそのまま使うため）
echo "🔴 Chromeを終了中..."
osascript -e 'quit app "Google Chrome"' 2>/dev/null
sleep 2

# Flaskをバックグラウンドで起動
echo "🚀 アプリを起動中（ポート: ${FLASK_PORT}）..."
python3 app.py &
FLASK_PID=$!

# Flask が起動するまで待機
echo "⏳ Flask 起動待機中..."
for i in $(seq 1 20); do
  if curl -s http://localhost:${FLASK_PORT} > /dev/null 2>&1; then
    echo "✅ Flask 起動確認（http://localhost:${FLASK_PORT}）"
    break
  fi
  sleep 1
done

# Flask確認後にChromeを起動（デバッグポート付き・専用プロファイル）
echo "🌐 Chromeを起動中..."
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
"$CHROME_BIN" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.aucfan-chrome-profile" \
  --no-first-run \
  --no-default-browser-check \
  --disable-sync \
  --disable-features=ChromeWhatsNewUI \
  2>/dev/null &
sleep 3

# デバッグポートが開いたか確認
for i in $(seq 1 10); do
  if curl -s http://localhost:9222/json > /dev/null 2>&1; then
    echo "✅ Chrome デバッグポート(9222)確認"
    break
  fi
  sleep 1
done

echo ""
echo "✅ 起動完了！"
echo ""
echo "次の手順:"
echo "  1. Chromeで新しいタブを開く（⌘T）"
echo "  2. AucFanにログイン・検索条件を設定・1ページ目を表示"
echo "  3. http://localhost:${FLASK_PORT} のタブに戻ってスクレイピング開始"
echo "     iPhone/iPad からは http://[MacのIP]:${FLASK_PORT}"
echo ""
echo "Ctrl+C → Flaskのみ停止（Chromeはそのまま残ります）"
echo ""

# Ctrl+C 時にFlaskだけ終了するハンドラ
trap "echo ''; echo '🛑 Flask停止中...'; kill $FLASK_PID 2>/dev/null; exit 0" INT TERM

# Flaskプロセスが終了するまで待機
wait $FLASK_PID
