#!/bin/bash
# GitHub アップロードスクリプト
cd "$(dirname "$0")"

echo "=== AucFan Tool → GitHub アップロード ==="

# ロックファイルが残っていたら削除
if [ -f ".git/index.lock" ]; then
    rm -f ".git/index.lock"
    echo "✓ index.lock を削除しました"
fi

# ステージング
git add -A

echo "✓ ファイルをステージングしました"

# コミットメッセージ引数チェック
if [ -z "$1" ]; then
    echo "使い方: ./git_push.sh 'コミットメッセージ'"
    exit 1
fi

git commit -m "$1"
echo "✓ コミット完了"

git push origin main
echo ""
echo "=== 完了！GitHub にアップロードされました ==="
