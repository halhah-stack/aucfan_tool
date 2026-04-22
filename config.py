"""
config.py - オークファンリサーチツール設定
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# Chrome デバッグ接続
# ─────────────────────────────────────────────
CHROME_DEBUG_HOST = os.getenv("CHROME_DEBUG_HOST", "127.0.0.1")
CHROME_DEBUG_PORT = int(os.getenv("CHROME_DEBUG_PORT", "9222"))

# ─────────────────────────────────────────────
# スクレイピング設定
# ─────────────────────────────────────────────
MIN_DELAY = float(os.getenv("MIN_DELAY", "3.0"))   # 最小待機秒数
MAX_DELAY = float(os.getenv("MAX_DELAY", "5.0"))   # 最大待機秒数
MAX_PAGES = int(os.getenv("MAX_PAGES", "500"))      # 最大ページ数
ITEMS_PER_PAGE = int(os.getenv("ITEMS_PER_PAGE", "50"))  # 1ページあたり件数
PAGE_LOAD_TIMEOUT = int(os.getenv("PAGE_LOAD_TIMEOUT", "30"))  # ページロードタイムアウト(秒)

# ─────────────────────────────────────────────
# フィルタリング設定
# ─────────────────────────────────────────────
MIN_PRICE = int(os.getenv("MIN_PRICE", "1000"))    # 最低価格（円）
MAX_PRICE = int(os.getenv("MAX_PRICE", "3000"))    # 最高価格（円）

# 箱サイズ除外（cm） - これを超えるものは除外
MAX_BOX_L = int(os.getenv("MAX_BOX_L", "45"))
MAX_BOX_W = int(os.getenv("MAX_BOX_W", "35"))
MAX_BOX_H = int(os.getenv("MAX_BOX_H", "20"))

# ─────────────────────────────────────────────
# 画像・同一商品グループ設定
# ─────────────────────────────────────────────
MIN_GROUP_SIZE = int(os.getenv("MIN_GROUP_SIZE", "5"))   # 仕入れ候補とする最小グループ件数
PHASH_THRESHOLD = int(os.getenv("PHASH_THRESHOLD", "5"))   # pHash同一判定閾値(0=完全一致, 大きいほど緩い)
IMAGE_DOWNLOAD_TIMEOUT = int(os.getenv("IMAGE_DOWNLOAD_TIMEOUT", "10"))  # 画像DLタイムアウト(秒)

# ─────────────────────────────────────────────
# Gemini API 設定
# ─────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_VISION = os.getenv("GEMINI_MODEL_VISION", "gemini-1.5-flash")   # 画像判定
GEMINI_MODEL_TEXT = os.getenv("GEMINI_MODEL_TEXT", "gemini-1.5-flash")        # テキスト判定
GEMINI_RPM_LIMIT = int(os.getenv("GEMINI_RPM_LIMIT", "14"))   # 無料枠: 15RPM → 安全のため14
GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "true").lower() == "true"

# ─────────────────────────────────────────────
# Flask 設定
# ─────────────────────────────────────────────
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")

# ─────────────────────────────────────────────
# 出力設定
# ─────────────────────────────────────────────
OUTPUT_BASE_DIR = os.getenv("OUTPUT_BASE_DIR", "リサーチ結果")

# ─────────────────────────────────────────────
# 商品ステータス定義
# ─────────────────────────────────────────────
STATUS_CANDIDATE = "candidate"    # 仕入れ候補（グループ5件以上）
STATUS_WAITING = "waiting"        # 確認待ち（詳細取得前）
STATUS_REVIEW = "review"          # 要確認（AI が安全リスクフラグ）
STATUS_OK = "ok"                  # OK（ユーザー承認済み）
STATUS_NG = "ng"                  # NG（除外）

STATUS_LABELS = {
    STATUS_CANDIDATE: "仕入れ候補",
    STATUS_WAITING: "確認待ち",
    STATUS_REVIEW: "要確認",
    STATUS_OK: "OK",
    STATUS_NG: "NG",
}

# ─────────────────────────────────────────────
# AucFan CSS セレクター設定
# サイトのデザイン変更時はここを更新してください
# ─────────────────────────────────────────────
SELECTORS = {
    # ───── 一覧ページ（AucFan 2026年版） ─────
    "list": {
        # 商品カード
        "item_cards": [
            "section.searchShowcaseType01",
            "section.clickResultItem",
        ],
        # 商品タイトル（カード内）
        "title": [
            "h2.searchShowcaseHd a.hdLink",
            "h2.searchShowcaseHd a",
            ".searchShowcaseHd a",
        ],
        # 落札価格
        "price": [
            "span.amount",
            ".searchShowcaseBlock span",
        ],
        # セラーID
        "seller": [
            "a.sellerLink",
            ".searchShowcaseDetails a.sellerLink",
        ],
        # サムネール画像（data-src-original で遅延読み込み）
        "image": [
            "img.itemsThum",
            ".showcaseItemsImg img",
        ],
        # 商品URL
        "url": [
            "h2.searchShowcaseHd a.hdLink",
            ".searchShowcaseHd a",
        ],
        # 次のページボタン
        "next_page": [
            "li.next a",
            "a[class*='next']",
            ".pager-next a",
        ],
    },

    # ───── 詳細ページ（aucview.aucfan.com） ─────
    "detail": {
        # 完全タイトル
        "full_title": [
            "h1.itemName",
            "h1[class*='title']",
            "h1[class*='name']",
            ".itemTitle",
            "h1",
        ],
        # 送料
        "shipping": [
            ".haisoFee",
            "[class*='shipping']",
            "[class*='postage']",
            "th:contains('送料') + td",
        ],
        # 詳細ページの複数画像
        "images": [
            ".itemImg img",
            ".itemImages img",
            ".photos img",
            "img[class*='itemImg']",
            "img[data-src-original]",
        ],
        # サイズ情報
        "size": [
            "th:contains('サイズ') + td",
            "th:contains('梱包') + td",
            "[class*='size']",
        ],
    }
}
