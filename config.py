"""
config.py — AucFan リサーチツール 全設定値

【変更方法】
  .env ファイルに KEY=VALUE 形式で記述すると上書き可能。
  コードの変更なしに設定を切り替えられる。

【主な設定カテゴリ】
  Chrome 接続      : CHROME_DEBUG_HOST / CHROME_DEBUG_PORT（start.sh と一致させること）
  スクレイピング   : MIN_DELAY / MAX_DELAY / MAX_PAGES / PAGE_LOAD_TIMEOUT
  価格フィルター   : MIN_PRICE / MAX_PRICE（一覧取得時に大まかに絞る）
  グループサイズ   : MIN_GROUP_SIZE / MIN_NEXT_CANDIDATE_SIZE 等
  pHash            : PHASH_THRESHOLD（類似度閾値、大きいほど緩い判定）/ MAX_PHASH_ITEMS（件数上限、超えたらスキップ）
  Gemini API       : GEMINI_API_KEY / GEMINI_MODEL_VISION / GEMINI_RPM_LIMIT
  Flask            : FLASK_PORT=5001 / FLASK_HOST=0.0.0.0
  除外キーワード   : EXCLUDE_TITLE_KEYWORDS（カンマ区切りで追加可能）
  CSS セレクター   : SELECTORS（AucFan のサイト改修時にここを更新する）
"""
import os
from pathlib import Path
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

# タイトルキーワードによる除外リスト（一覧取得時点で弾く）
# キーワードリサーチ・セラー分析の両方で適用される
# .env の EXCLUDE_TITLE_KEYWORDS にカンマ区切りで追加可能
_EXCLUDE_KEYWORDS_DEFAULT = [
    "チケット", "金券", "招待券", "商品券", "ギフト券", "クーポン", "優待券",
    "サイン色紙", "直筆サイン", "サイン入り", "色紙", "直筆", "autograph", "署名",
    # ─── 身体に使用するもの（体への影響リスク） ───
    # ヘアケア
    "シャンプー", "リンス", "コンディショナー", "トリートメント",
    "ヘアカラー", "白髪染め", "白髪隠し", "ブリーチ", "パーマ液",
    "育毛剤", "育毛", "発毛", "養毛", "ヘアトニック", "ヘアオイル", "ヘアワックス", "ヘアスプレー",
    # スキンケア・化粧品
    "化粧水", "乳液", "美容液", "クレンジング", "洗顔料", "洗顔フォーム",
    "日焼け止め", "UVクリーム", "ファンデーション", "BBクリーム", "CCクリーム",
    "口紅", "リップ", "アイシャドウ", "マスカラ", "アイライナー",
    "化粧品", "コスメ", "スキンケア",
    # フェイスマスク・パック
    "マスク", "フェイスマスク", "フェイスパック", "パック",
    # ボディケア
    "ボディソープ", "ボディウォッシュ", "ボディクリーム", "ボディローション",
    "除毛クリーム", "脱毛クリーム", "除毛", "ムダ毛",
    "制汗剤", "デオドラント", "制汗スプレー",
    # オーラルケア
    "歯磨き粉", "歯磨き", "歯みがき", "マウスウォッシュ", "洗口液",
    # サプリ・健康食品（体内に入るもの）
    "サプリメント", "サプリ", "プロテイン", "栄養補助食品", "健康食品",
    "ダイエット食品", "置き換えダイエット",
    # 医薬品・医薬部外品
    "医薬品", "医薬部外品", "塗り薬", "湿布", "目薬", "点眼",
    "消毒液", "消毒スプレー", "殺菌",
    # 衣類・装着品
    "ヘルメット",
    # ファッション・衣類
    "羊皮", "フライトジャケット", "ムートン", "コート", "本革", "防寒服", "ラムレザー",
    # 危険物・高圧ガス
    "エアコンガス", "冷媒ガス", "フロンガス", "HFCガス", "R134a", "R410A", "R32",
    "ガス缶", "スプレー缶", "ガスボンベ", "高圧ガス", "危険物",
    # 3M
    "3M", "スリーエム",
    # レーザー機器（危険物・規制品）
    "レーザー", "レーザーポインター", "レーザー照射", "レーザーカッター", "レーザー脱毛",
    # ─── 食品入りセット・詰め合わせ（調理器具単体はOK） ───
    "鍋セット", "食材セット", "詰め合わせ", "お取り寄せ", "グルメセット", "食べ比べ", "お試しセット",
    # ─── 食品・食材・飲料（包括除外） ───
    # 汎用ワード
    "食品", "食材", "惣菜", "弁当", "生鮮",
    # 水産物・貝類
    "サザエ", "アワビ", "ホタテ", "ハマグリ", "アサリ", "カキ", "ホッキ", "ホヤ",
    "ウニ", "イクラ", "タラコ", "明太子", "しらす", "ちりめん",
    "エビ", "海老", "ロブスター", "ズワイガニ", "毛ガニ", "タラバガニ",
    "カニ", "蟹",
    "マグロ", "サーモン", "鮭", "サバ", "アジ", "ブリ", "タイ", "ヒラメ", "カレイ",
    "鰻", "うなぎ", "アナゴ", "タコ", "イカ", "烏賊",
    # お菓子・スイーツ
    "お菓子", "スイーツ", "ケーキ", "チョコ", "クッキー", "せんべい",
    # 麺類・主食・粉類
    "ラーメン", "そば", "うどん", "パスタ", "米", "精米", "小麦粉",
    # 調味料・加工食品
    "砂糖", "塩", "醤油", "みそ", "酢", "料理酒", "ドレッシング", "ソース", "調味料",
    "缶詰", "瓶詰め", "レトルト", "冷凍食品",
    # 農産物・肉類
    "牛肉", "豚肉", "鶏肉", "ラム肉", "馬肉", "ジビエ",
    "野菜", "果物", "フルーツ",
    "メロン", "スイカ", "桃", "梨", "りんご", "みかん", "いちご", "ぶどう",
    "きのこ", "松茸", "トリュフ",
    # 飲料
    "ビール", "ワイン", "日本酒", "焼酎", "ウイスキー", "ブランデー", "シャンパン", "酒",
    "飲料", "ジュース", "お茶", "コーヒー豆",
    # ─── 生体・動物・家禽（AucFanに出品される生き物全般） ───
    # ニワトリ品種名（「ポーリッシュバフ」等の工具名と被るケースに対応）
    "有髭",          # bearded系品種の共通ワード（工具名にはほぼ使われない）
    "ニワトリ", "鶏", "チャボ", "ひよこ", "雛", "種鶏", "採卵鶏", "烏骨鶏",
    "アローカナ", "プリマスロック", "レグホン", "コーチン", "名古屋コーチン",
    # 生体・ペット全般
    "生体", "生き物", "観賞魚", "熱帯魚", "金魚", "メダカ", "錦鯉", "グッピー",
    "カブトムシ", "クワガタ", "カナリア", "文鳥", "インコ", "オウム",
    "ハムスター", "モルモット", "うさぎ", "ウサギ",
    # 植物・苗・種（生体扱い）
    "苗", "種子", "球根", "多肉植物", "サボテン",
    # NPB 12球団（セ・リーグ）
    "巨人", "ジャイアンツ", "読売",
    "阪神", "タイガース",
    "横浜", "ベイスターズ", "DeNA",
    "広島", "カープ",
    "中日", "ドラゴンズ",
    "ヤクルト", "スワローズ",
    # NPB 12球団（パ・リーグ）
    "日本ハム", "ファイターズ",
    "楽天", "イーグルス",
    "西武", "ライオンズ",
    "ロッテ", "マリーンズ",
    "ソフトバンク", "ホークス",
    "オリックス", "バファローズ",
]
_extra = os.getenv("EXCLUDE_TITLE_KEYWORDS", "")
EXCLUDE_TITLE_KEYWORDS: list = _EXCLUDE_KEYWORDS_DEFAULT + [
    k.strip() for k in _extra.split(",") if k.strip()
]

# ─────────────────────────────────────────────
# タイトル先頭メーカー名除外（_parse_item_card でスキャン）
# スペース区切りのトークン先頭1〜2番目に含まれていたら除外
# ─────────────────────────────────────────────

# 先頭に来ても「状態情報」として読み飛ばすワード
TITLE_STATUS_WORDS = {
    "送料無料", "未使用", "新品", "中古", "未開封", "美品",
    "訳あり", "ジャンク", "即決", "即納", "即日",
}

# 先頭1〜2トークン目に来たら除外する既知メーカー・ブランド名
# （大文字小文字混在あり → 比較時に lower() で正規化する）
_EXCLUDE_MAKERS_DEFAULT = [
    # 家電
    "HITACHI", "日立",
    "Panasonic", "パナソニック",
    "SHARP", "シャープ",
    "SONY", "ソニー",
    "Toshiba", "東芝",
    "Mitsubishi", "三菱",
    "Fujitsu", "富士通",
    # カメラ・映像
    "Canon", "キヤノン", "キャノン",
    "Nikon", "ニコン",
    "OLYMPUS", "オリンパス",
    "Fujifilm", "富士フイルム",
    # 自動車
    "Toyota", "トヨタ",
    "Honda", "ホンダ",
    "Yamaha", "ヤマハ",
    "Suzuki", "スズキ",
    "Kawasaki", "カワサキ",
    # IT・AV
    "Apple",
    "Samsung", "サムスン",
    "LG",
    "Brother", "ブラザー",
    "Epson", "エプソン",
    # その他
    "3M", "スリーエム",
    "Dyson", "ダイソン",
]
_extra_makers = os.getenv("EXCLUDE_MAKER_KEYWORDS", "")
# lower() で比較するため、保存は lower 化済みのセットとして持つ
EXCLUDE_MAKER_KEYWORDS: set = {
    w.lower() for w in _EXCLUDE_MAKERS_DEFAULT
} | {
    k.strip().lower() for k in _extra_makers.split(",") if k.strip()
}

# ─────────────────────────────────────────────
# トレーディングカード関連キーワード
# タイトルにこれらが含まれる場合は Gemini 判定に委ねる（needs_card_check フラグ付与）
# カード本体 → excluded / カードケース・スリーブ等アクセサリー → ok
# ─────────────────────────────────────────────
TRADING_CARD_KEYWORDS: set = {
    "ポケモンカード", "ポケカ",
    "遊戯王",
    "MTG", "マジック・ザ・ギャザリング",
    "デュエマ", "デュエルマスターズ",
    "ワンピースカード",
    "ドラゴンボールカード",
    "バトルスピリッツ",
    "ヴァンガード", "カードファイト",
    "トレーディングカード", "トレカ",
    "シングルカード",
    "封入", "パック開封",
}

# ─────────────────────────────────────────────
# 自動車・バイク・カー用品キーワード
# タイトルにこれらが含まれる場合はメーカー名除外・Geminiブランド判定をスキップ
# （車種専用品・カー用品はToyota/Honda等のメーカー名が付いていても合法的に流通する）
# ─────────────────────────────────────────────
AUTOMOTIVE_KEYWORDS: set = {
    # 車種名
    "ハイエース", "プリウス", "アルファード", "ヴォクシー", "ノア",
    "クラウン", "カローラ", "ランクル", "ランドクルーザー", "エスティマ",
    "シエンタ", "RAV4", "CX-5", "フィット", "ステップワゴン",
    "セレナ", "エルグランド", "ハスラー", "ジムニー", "N-BOX",
    "タント", "スペーシア",
    # カー用品
    "カーナビ", "ドライブレコーダー", "ドラレコ", "カーオーディオ", "カーステ",
    "ETC", "シートカバー", "フロアマット", "カーマット",
    "タイヤ", "ホイール", "ミラー", "ワイパー",
    "バッテリー充電器", "オイルフィルター", "エアフィルター", "スタッドレス",
    # バイク・二輪
    "バイク", "スクーター", "原付", "グローブ", "チェーン",
}

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

# ローカル画像キャッシュ（Google Driveの外に保存することで高速表示・別Mac閲覧に対応）
# 各Macが個別に持つキャッシュ。セッションをロードすると不足画像をバックグラウンドで自動DL。
# .env に LOCAL_IMAGE_CACHE_DIR=/path/to/dir を記載して変更可能。
LOCAL_IMAGE_CACHE_DIR = Path(os.path.expanduser(
    os.getenv("LOCAL_IMAGE_CACHE_DIR", "~/Downloads/aucfan_images")
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
# Flask 設定
# ─────────────────────────────────────────────
FLASK_PORT = int(os.getenv("FLASK_PORT", "5001"))
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")

# ─────────────────────────────────────────────
# 出力設定
# ─────────────────────────────────────────────
# セッションデータの保存先。
# デフォルトは Google Drive（2拠点からアクセス可能）。
# Google Drive for Desktop がインストールされていない環境では
# .env に OUTPUT_BASE_DIR=リサーチ結果 と記載してローカルに切り替え可能。
_GDRIVE_ROOT = os.path.expanduser(
    "~/Library/CloudStorage/"
    "GoogleDrive-shinozakistore@gmail.com/"
    "マイドライブ/AucFanToolData"
)
_GDRIVE_BASE = os.path.join(_GDRIVE_ROOT, "リサーチ結果")
OUTPUT_BASE_DIR = os.getenv("OUTPUT_BASE_DIR", _GDRIVE_BASE)

# マスターセラーリストも Google Drive に保存（2拠点で共有）。
# Google Drive 未接続時はローカルの data/sellers_master.json にフォールバック。
_GDRIVE_SELLERS = os.path.join(_GDRIVE_ROOT, "sellers_master.json")
SELLERS_MASTER_PATH = os.getenv("SELLERS_MASTER_PATH", _GDRIVE_SELLERS)

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
