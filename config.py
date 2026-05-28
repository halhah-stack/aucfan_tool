"""
config.py — AucFan リサーチツール 全設定値

【変更方法】
  .env ファイルに KEY=VALUE 形式で記述すると上書き可能。
  コードの変更なしに設定を切り替えられる。

【除外ルールのメンテナンス】
  rules.yaml を直接編集してください（コードの変更不要）。
  変更後は bash start.sh で再起動するだけで反映されます。
  → title_keywords    : タイトルキーワード除外リスト
  → maker_keywords    : メーカー・ブランド名除外リスト
  → trading_card_keywords / automotive_keywords : 判定補助リスト
  → custom_rules      : Gemini学習済みカスタムルール

【主な設定カテゴリ】
  Chrome 接続      : CHROME_DEBUG_HOST / CHROME_DEBUG_PORT（start.sh と一致させること）
  スクレイピング   : MIN_DELAY / MAX_DELAY / MAX_PAGES / PAGE_LOAD_TIMEOUT
  価格フィルター   : MIN_PRICE / MAX_PRICE（一覧取得時に大まかに絞る）
  グループサイズ   : MIN_GROUP_SIZE / MIN_NEXT_CANDIDATE_SIZE 等
  pHash            : PHASH_THRESHOLD（類似度閾値、大きいほど緩い判定）/ MAX_PHASH_ITEMS（件数上限、超えたらスキップ）
  Gemini API       : GEMINI_API_KEY / GEMINI_MODEL_VISION / GEMINI_RPM_LIMIT
  Flask            : FLASK_PORT=5001 / FLASK_HOST=0.0.0.0
  CSS セレクター   : SELECTORS（AucFan のサイト改修時にここを更新する）
"""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# rules.yaml 読み込み（除外ルール一元管理）
# ─────────────────────────────────────────────
def _load_rules() -> dict:
    """rules.yaml を読み込む。ファイルがなければ空の辞書を返す"""
    rules_path = Path(__file__).parent / "rules.yaml"
    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data
    except FileNotFoundError:
        import logging
        logging.getLogger(__name__).warning("rules.yaml が見つかりません。デフォルト値で動作します。")
        return {}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"rules.yaml 読み込みエラー: {e}")
        return {}

_RULES = _load_rules()

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

# ─────────────────────────────────────────────
# タイトルキーワード除外（rules.yaml から読み込み）
# ─────────────────────────────────────────────
# メンテナンスは rules.yaml を直接編集してください
EXCLUDE_TITLE_KEYWORDS: list = _RULES.get("title_keywords", [])

# ─────────────────────────────────────────────
# タイトル先頭メーカー名除外（rules.yaml から読み込み）
# ─────────────────────────────────────────────

# 先頭に来ても「状態情報」として読み飛ばすワード
TITLE_STATUS_WORDS = {
    "送料無料", "未使用", "新品", "中古", "未開封", "美品",
    "訳あり", "ジャンク", "即決", "即納", "即日",
}

# lower() で比較するため、保存は lower 化済みのセットとして持つ
EXCLUDE_MAKER_KEYWORDS: set = {
    w.lower() for w in _RULES.get("maker_keywords", [])
}

# ─────────────────────────────────────────────
# トレーディングカード関連キーワード（rules.yaml から読み込み）
# ─────────────────────────────────────────────
TRADING_CARD_KEYWORDS: set = set(_RULES.get("trading_card_keywords", []))

# ─────────────────────────────────────────────
# 自動車・バイク・カー用品キーワード（rules.yaml から読み込み）
# ─────────────────────────────────────────────
AUTOMOTIVE_KEYWORDS: set = set(_RULES.get("automotive_keywords", []))

# 箱サイズ除外（cm） - これを超えるものは除外
MAX_BOX_L = int(os.getenv("MAX_BOX_L", "45"))
MAX_BOX_W = int(os.getenv("MAX_BOX_W", "35"))
MAX_BOX_H = int(os.getenv("MAX_BOX_H", "20"))

# ─────────────────────────────────────────────
# 画像・同一商品グループ設定
# ─────────────────────────────────────────────
MIN_GROUP_SIZE = int(os.getenv("MIN_GROUP_SIZE", "5"))   # 仕入れ候補とする最小グループ件数
MIN_NEXT_CANDIDATE_SIZE = int(os.getenv("MIN_NEXT_CANDIDATE_SIZE", "4"))  # 次期候補とする最小グループ件数
SELLER_DETAIL_MIN_GROUP = int(os.getenv("SELLER_DETAIL_MIN_GROUP", "3"))  # セラー分析で詳細取得・Gemini判定する最小グループ件数
VISION_MIN_GROUP_SIZE = int(os.getenv("VISION_MIN_GROUP_SIZE", "4"))     # pHash後にVision判定するグループの最小件数
MASTER_SELLER_MIN_GROUP_SIZE = int(os.getenv("MASTER_SELLER_MIN_GROUP_SIZE", "2"))  # マスターリストに追加するセラーの最小グループサイズ
PHASH_THRESHOLD = int(os.getenv("PHASH_THRESHOLD", "2"))   # pHash同一判定閾値(0=完全一致, 大きいほど緩い。デフォルト2=ほぼ完全一致のみグループ化)
MAX_PHASH_ITEMS = int(os.getenv("MAX_PHASH_ITEMS", "15000"))
# pHashグループ化の件数上限。超えると比較回数が爆発（N×N/2）してフリーズするため自動スキップ。
# スキップ時はターミナルに「>>> pHash スキップ <<<」と表示される。
# セラー数が多い場合（例: 20セラー×2,500件=50,000件）はスキップが発動する。
IMAGE_DOWNLOAD_TIMEOUT = int(os.getenv("IMAGE_DOWNLOAD_TIMEOUT", "10"))  # 画像DLタイムアウト(秒)

# ─────────────────────────────────────────────
# Google Drive ルートパス 自動検出
# ─────────────────────────────────────────────
# ミラーリングモード・ストリーミングモード・どのMacユーザーでも自動対応。
# .env に OUTPUT_BASE_DIR を明示した場合はそちらが優先される。

def _find_gdrive_aucfan_root() -> str:
    """AucFanToolData フォルダのパスを自動検出して返す。
    見つからない場合は None を返す。
    検出順序:
      1. ミラーリングモード: ~/マイドライブ*/AucFanToolData（AucFanToolData が存在すれば有効）
      2. ストリーミングモード: ~/Library/CloudStorage/GoogleDrive-*/マイドライブ/AucFanToolData
    """
    home = Path.home()
    # 1. ミラーリングモード（全角カッコ付き含む）
    # AucFanToolData フォルダが存在すれば有効（リサーチ結果の有無は問わない）
    for candidate in sorted(home.glob("マイドライブ*")):
        p = candidate / "AucFanToolData"
        if p.exists():
            return str(p)
    # 2. ストリーミングモード
    cloud = home / "Library" / "CloudStorage"
    if cloud.exists():
        for gd in sorted(cloud.glob("GoogleDrive-*")):
            p = gd / "マイドライブ" / "AucFanToolData"
            if p.exists():
                return str(p)
    return None

_GDRIVE_ROOT = _find_gdrive_aucfan_root() or os.path.expanduser(
    "~/マイドライブ（shinozakistore@gmail.com）/AucFanToolData"
)
_GDRIVE_BASE = os.path.join(_GDRIVE_ROOT, "リサーチ結果")
OUTPUT_BASE_DIR = os.getenv("OUTPUT_BASE_DIR", _GDRIVE_BASE)

# Excel リサーチシートの保存先（スクレイピングデータと分離）
# AucFanToolData/リサーチシート/ にExcelファイルをまとめる。
# スクレイピング画像（リサーチ結果/）と同階層に置くことで誤削除を防ぐ。
EXCEL_BASE_DIR = os.getenv("EXCEL_BASE_DIR", os.path.join(_GDRIVE_ROOT, "リサーチシート"))

# マスターセラーリストも Google Drive に保存（2拠点で共有）。
# Google Drive 未接続時はローカルの data/sellers_master.json にフォールバック。
_GDRIVE_SELLERS = os.path.join(_GDRIVE_ROOT, "sellers_master.json")
SELLERS_MASTER_PATH = os.getenv("SELLERS_MASTER_PATH", _GDRIVE_SELLERS)

# ─────────────────────────────────────────────
# Google Drive アップロード設定
# ─────────────────────────────────────────────
# GDRIVE_UPLOAD_ENABLED=true  : scraper Mac が画像を GDrive API で直接アップロード（デフォルト）
# GDRIVE_UPLOAD_ENABLED=false : GDrive へのアップロードを完全に無効化
#   → GDrive を使わないスタンドアローン運用、または将来的に別の同期手段に切り替える場合
#   → credentials.json / token.json が不要になる
#   → google-api-python-client 等の GDrive 系ライブラリも実質不要
GDRIVE_UPLOAD_ENABLED = os.getenv("GDRIVE_UPLOAD_ENABLED", "true").lower() == "true"

# ─────────────────────────────────────────────
# サイトロール設定
# ─────────────────────────────────────────────
# SITE_ROLE=scraper : スクレイピング側（デフォルト）
#   - 画像をローカル img_cache/ に保存
#   - GDRIVE_UPLOAD_ENABLED=true のとき GDrive にもアップロード
# SITE_ROLE=reader  : 閲覧側
#   - GDrive ミラーリング済みフォルダを画像ソースとして使う
#   - GDriveアップロードは不要（ミラーリングで自動同期）
# どちらのMacでも SITE_ROLE を切り替えるだけで役割を入れ替え可能。
SITE_ROLE = os.getenv("SITE_ROLE", "scraper")  # デフォルト: scraper

# ローカル画像キャッシュ（アプリはこちらから読む）
# SITE_ROLE で自動設定。個別に上書きしたい場合は .env に LOCAL_IMAGE_CACHE_DIR= を記載。
if SITE_ROLE == "reader":
    # reader: GDriveミラーリング済みのリサーチ結果フォルダを画像ソースとして使う（自動検出）
    _default_image_cache = _GDRIVE_BASE  # = AucFanToolData/リサーチ結果/（自動検出済み）
else:
    # scraper: ローカルの img_cache/ に保存
    _default_image_cache = str(Path(__file__).parent / "img_cache")

LOCAL_IMAGE_CACHE_DIR = Path(os.path.expanduser(
    os.getenv("LOCAL_IMAGE_CACHE_DIR", _default_image_cache)
))

# ─────────────────────────────────────────────
# Gemini API 設定
# ─────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_VISION = os.getenv("GEMINI_MODEL_VISION", "gemini-1.5-flash")   # 画像判定
GEMINI_MODEL_TEXT = os.getenv("GEMINI_MODEL_TEXT", "gemini-1.5-flash")        # テキスト判定
GEMINI_RPM_LIMIT = int(os.getenv("GEMINI_RPM_LIMIT", "14"))   # 無料枠: 15RPM → 安全のため14
GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "true").lower() == "true"

# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# 1688 → 円 換算係数
# ─────────────────────────────────────────────
# 単価(元) × CNY_TO_JPY_RATE = 原価(円)
# 送料・関税・代行手数料等を含む独自係数。.env で変更可能。
CNY_TO_JPY_RATE = int(os.getenv("CNY_TO_JPY_RATE", "35"))

# ─────────────────────────────────────────────
# Amazon FBA 料金シミュレータ URL
# ─────────────────────────────────────────────
# URLが変更された場合は .env に REVCAL_URL=新しいURL を追記して対応。
REVCAL_URL = os.getenv(
    "REVCAL_URL",
    "https://sellercentral.amazon.co.jp/revcal?ref=RC2nonlogin"
)

# ─────────────────────────────────────────────
# 仕入れ判断基準
# ─────────────────────────────────────────────
# 利益率(%) と 利益(円) のどちらかを満たせば ◎ GO
PROFIT_RATE_THRESHOLD = float(os.getenv("PROFIT_RATE_THRESHOLD", "25"))   # %
PROFIT_YEN_THRESHOLD  = int(os.getenv("PROFIT_YEN_THRESHOLD",   "450"))   # 円

# Flask 設定
# ─────────────────────────────────────────────
FLASK_PORT = int(os.getenv("FLASK_PORT", "5001"))
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")

# ─────────────────────────────────────────────
# STEP2/3 セラーリサーチ 商品状態フィルター
# ─────────────────────────────────────────────
# True のとき、AucFan 一覧の「商品状態」が新品系ワードの商品のみを取得する。
# .env に SELLER_NEW_ONLY=false と書けば全件対象に戻せる。
SELLER_NEW_ONLY = os.getenv("SELLER_NEW_ONLY", "true").lower() == "true"

# 新品とみなす商品状態ワード（AucFan の「商品状態」欄に表示されるテキスト）
SELLER_NEW_CONDITIONS = [w.strip() for w in os.getenv(
    "SELLER_NEW_CONDITIONS", "新品,未使用,未開封,未着用"
).split(",") if w.strip()]

# セラー単位の中古スキップ閾値
# STEP2/3 スクレイピング中、1セラーで中古商品がこの件数を超えたらそのセラーを打ち切り、
# 取得済みデータを破棄して次のセラーへ進む。
# 0 = スキップしない（アイテム単位フィルターのみ）
# 推奨: 3〜10（偶発的な1〜2件の中古を許容しつつ、中古主体セラーを除外）
SELLER_USED_SKIP_THRESHOLD = int(os.getenv("SELLER_USED_SKIP_THRESHOLD", "5"))

# ─────────────────────────────────────────────
# 商品ステータス定義
# ─────────────────────────────────────────────
STATUS_CANDIDATE = "candidate"          # 仕入れ候補（グループ MIN_GROUP_SIZE 件以上）
STATUS_NEXT_CANDIDATE = "next_candidate"  # 次期候補（グループ MIN_NEXT_CANDIDATE_SIZE 件以上）
STATUS_WAITING = "waiting"              # 確認待ち（詳細取得前）
STATUS_REVIEW = "review"                # 要確認（AI が安全リスクフラグ）
STATUS_OK = "ok"                        # OK（ユーザー承認済み）
STATUS_NG = "ng"                        # NG（除外）

STATUS_LABELS = {
    STATUS_CANDIDATE: "仕入れ候補",
    STATUS_NEXT_CANDIDATE: "次期候補",
    STATUS_WAITING: "確認待ち",
    STATUS_REVIEW: "要確認",
    STATUS_OK: "OK",
    STATUS_NG: "NG",
}

# ─────────────────────────────────────────────
# AucFan CSS セレクター設定
#
# AucFan のサイト改修時にセレクターが変わる場合はここを更新する。
# 各セレクターはリスト形式で複数候補を持ち、先頭から順に試みる（フォールバック）。
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
