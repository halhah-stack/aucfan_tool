#!/bin/bash
# ──────────────────────────────────────────────────────────────────
# launch_chrome.sh
# AucFan リサーチツール用 Chrome 起動スクリプト（Mac 専用）
#
# 使い方:
#   1. このスクリプトを実行する前に Chrome を完全に終了する
#   2. bash launch_chrome.sh
#   3. 開いた Chrome で AucFan にログインし、検索条件を設定して
#      1ページ目を表示した状態にする
#   4. 別ターミナルで: python app.py
# ──────────────────────────────────────────────────────────────────

CHROME_APP="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEBUG_PORT=9222

# Chrome が既に起動していないか確認
if lsof -i :${DEBUG_PORT} > /dev/null 2>&1; then
    echo "⚠️  ポート ${DEBUG_PORT} は既に使用中です。"
    echo "   既存の Chrome デバッグセッションが起動中かもしれません。"
    echo "   そのまま python app.py を実行できます。"
    exit 0
fi

if [ ! -f "$CHROME_APP" ]; then
    echo "❌ Chrome が見つかりません: $CHROME_APP"
    echo "   Chrome のパスを確認してください。"
    exit 1
fi

echo "🚀 Chrome をリモートデバッグモードで起動します..."
echo "   デバッグポート: ${DEBUG_PORT}"
echo ""

"$CHROME_APP" \
    --remote-debugging-port=${DEBUG_PORT} \
    --no-first-run \
    --no-default-browser-check \
    2>/dev/null &

sleep 2
echo "✅ Chrome が起動しました。"
echo ""
echo "次の手順:"
echo "  1. AucFan (https://aucfan.com) にログイン"
echo "  2. 検索条件（キーワード・価格帯・カテゴリ）を設定"
echo "  3. 1ページ目の検索結果を表示した状態にする"
echo "  4. 別のターミナルで: python app.py"
