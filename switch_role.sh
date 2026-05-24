#!/bin/bash
# switch_role.sh — scraper / reader / standalone の切り替えスクリプト
#
# 使い方:
#   bash switch_role.sh scraper     # スクレイピング専用（GDriveアップロードあり）
#   bash switch_role.sh reader      # 閲覧専用（GDriveミラーリングから読む）
#   bash switch_role.sh standalone  # 1台完結（GDriveなし・ローカル保存）
#
# 実行するだけで .env を書き換えます。
# その後 bash start.sh でアプリを再起動してください。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
MODE="${1:-}"

# ─────────────────────────────────────────────
# ヘルプ
# ─────────────────────────────────────────────
usage() {
    cat <<'EOF'
使い方: bash switch_role.sh [モード]

  scraper     スクレイピング専用（GDriveアップロードあり）
  reader      閲覧専用（GDriveミラーリングから読む）
  standalone  1台完結（GDriveなし・ローカルに保存）

例:
  bash switch_role.sh scraper
  bash switch_role.sh reader
  bash switch_role.sh standalone
EOF
}

if [[ -z "$MODE" ]]; then
    usage
    exit 1
fi

# ─────────────────────────────────────────────
# .env がなければ .env.example からコピー
# ─────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$SCRIPT_DIR/.env.example" ]]; then
        cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
        echo "📄 .env.example から .env を作成しました"
    else
        touch "$ENV_FILE"
    fi
fi

# ─────────────────────────────────────────────
# ヘルパー: .env のキーを書き換える
#   既存行（コメントアウト含む）があれば上書き
#   なければ末尾に追加
# ─────────────────────────────────────────────
set_env() {
    local key="$1"
    local val="$2"
    if grep -qE "^#*${key}=" "$ENV_FILE"; then
        sed -i '' "s|^#*${key}=.*|${key}=${val}|" "$ENV_FILE"
    else
        echo "${key}=${val}" >> "$ENV_FILE"
    fi
}

# ヘルパー: キーをコメントアウトする（不要な行を無効化）
comment_out_key() {
    local key="$1"
    if grep -qE "^${key}=" "$ENV_FILE"; then
        sed -i '' "s|^${key}=|#${key}=|" "$ENV_FILE"
    fi
}

# ─────────────────────────────────────────────
# モード別の処理
# ─────────────────────────────────────────────
case "$MODE" in

  scraper)
    echo ""
    echo "🔵 scraper モードに切り替えます"
    echo "   → スクレイピング実行 + GDrive へアップロード"
    echo ""
    set_env "SITE_ROLE" "scraper"
    set_env "GDRIVE_UPLOAD_ENABLED" "true"
    comment_out_key "OUTPUT_BASE_DIR"
    comment_out_key "SELLERS_MASTER_PATH"
    echo "✅ .env を更新しました"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📋 残りの手動作業（以下を順番に）:"
    echo ""
    echo "  1. Google Drive アプリを「ストリーミング」モードに変更"
    echo "     Google Drive アプリ → 環境設定 → マイドライブの同期オプション"
    echo "     →「ファイルをストリーミング」を選択 → 保存"
    echo "     ※ すでにストリーミングモードなら不要"
    echo ""
    echo "  2. credentials.json を aucfan_tool/ に配置"
    echo "     Google Cloud Console からダウンロードした"
    echo "     client_secret_xxx.json を credentials.json にリネームして配置"
    echo "     ※ すでに配置済みなら不要"
    echo ""
    echo "  3. GDrive 初回認証（credentials.json を新たに配置した場合のみ）"
    echo "     cd ~/Downloads/aucfan_tool"
    echo "     .venv/bin/python setup_gdrive_auth.py"
    echo ""
    echo "  4. アプリ再起動"
    echo "     bash start.sh"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ;;

  reader)
    echo ""
    echo "🟢 reader モードに切り替えます"
    echo "   → GDrive ミラーリングから閲覧・Excel出力"
    echo ""
    set_env "SITE_ROLE" "reader"
    set_env "GDRIVE_UPLOAD_ENABLED" "false"
    comment_out_key "OUTPUT_BASE_DIR"
    comment_out_key "SELLERS_MASTER_PATH"
    echo "✅ .env を更新しました"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📋 残りの手動作業（以下を順番に）:"
    echo ""
    echo "  1. Google Drive アプリを「ミラーリング」モードに変更"
    echo "     Google Drive アプリ → 環境設定 → マイドライブの同期オプション"
    echo "     →「このデバイスにファイルをミラーリング」を選択 → 保存"
    echo "     ※ すでにミラーリングモードなら不要"
    echo ""
    echo "  2. GDrive の同期完了を待つ"
    echo "     （同期状況は Google Drive アプリのアイコンで確認）"
    echo ""
    echo "  3. アプリ再起動"
    echo "     bash start.sh"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ;;

  standalone)
    echo ""
    echo "🟡 standalone モードに切り替えます"
    echo "   → GDrive 不要・1台だけでスクレイピング＋閲覧"
    echo ""
    set_env "SITE_ROLE" "scraper"
    set_env "GDRIVE_UPLOAD_ENABLED" "false"
    set_env "OUTPUT_BASE_DIR" "リサーチ結果"
    set_env "SELLERS_MASTER_PATH" "data/sellers_master.json"
    echo "✅ .env を更新しました"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📋 残りの手動作業:"
    echo ""
    echo "  1. アプリ再起動（それだけでOK）"
    echo "     bash start.sh"
    echo ""
    echo "  ※ リサーチ結果は ~/Downloads/aucfan_tool/リサーチ結果/ に保存されます"
    echo "  ※ credentials.json / token.json / GDrive アプリ すべて不要です"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ;;

  *)
    echo "❌ 不明なモード: $MODE"
    echo ""
    usage
    exit 1
    ;;
esac

echo ""
echo "現在の .env（関連行）:"
grep -E "^(SITE_ROLE|GDRIVE_UPLOAD_ENABLED|OUTPUT_BASE_DIR|SELLERS_MASTER_PATH)=" "$ENV_FILE" || echo "  （設定なし）"
echo ""
