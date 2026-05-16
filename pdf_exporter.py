"""
pdf_exporter.py — AucFan 仕入れ候補 PDF エクスポーター

スクレイピング完了時に自動生成する。
  対象  : 仕入れ候補（candidate）・次期候補（next_candidate）
  ソート : 同一件数 多い順 → 合計価格 高い順
  レイアウト: A4縦 2カラムグリッド（HTML画面と同等構成）
"""
from __future__ import annotations

import io
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── ページ・カラム定数 (mm) ───────────────────────────
PAGE_W, PAGE_H = 210.0, 297.0
MARGIN         = 8.0          # 上下左右余白
COL_GAP        = 3.0          # カラム間隔
COLS           = 2
COL_W          = (PAGE_W - MARGIN * 2 - COL_GAP) / COLS   # ≈ 90.5 mm

CARD_GAP_Y     = 2.5          # カード縦間隔

# ─── カード各セクション高さ (mm) ──────────────────────
STATUS_H  = 6.5    # ステータスバー（緑/青帯）
IMG_H     = 20.0   # 画像ストリップ
TITLE_H   = 9.0    # タイトル2行
PRICE_H   = 8.0    # 価格行（合計 + 内訳）
SELLER_H  = 5.5    # セラー行
CARD_H    = STATUS_H + IMG_H + TITLE_H + PRICE_H + SELLER_H  # ≈ 49 mm

MAX_IMGS  = 4      # カードあたり最大サムネイル数
IMG_PX    = 80     # サムネイル解像度 (px, 正方形)

# ─── ステータス定義 ───────────────────────────────────
STATUS_TARGET = {"candidate", "next_candidate"}
STATUS_BG = {
    "candidate":      (22, 163, 74),    # green-600
    "next_candidate": (37, 99, 235),    # blue-600
}
STATUS_LABEL = {
    "candidate":      "仕入れ候補",
    "next_candidate": "次期候補",
}

# ─── macOS 日本語フォント候補 ────────────────────────
_JP_FONT_PATHS = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
    "/Library/Fonts/ヒラギノ角ゴ ProN W3.otf",
    "/System/Library/Fonts/Supplemental/Hiragino Sans GB.ttc",
]


def _find_jp_font() -> Optional[str]:
    for p in _JP_FONT_PATHS:
        if Path(p).exists():
            return p
    return None


def _make_thumb(img_path: Path) -> Optional[bytes]:
    """画像を正方形サムネイルにリサイズして JPEG bytes を返す。失敗時 None。"""
    try:
        from PIL import Image
        with Image.open(img_path) as im:
            im = im.convert("RGB")
            im.thumbnail((IMG_PX, IMG_PX), Image.LANCZOS)
            sq = Image.new("RGB", (IMG_PX, IMG_PX), (225, 225, 225))
            ox = (IMG_PX - im.width) // 2
            oy = (IMG_PX - im.height) // 2
            sq.paste(im, (ox, oy))
            buf = io.BytesIO()
            sq.save(buf, "JPEG", quality=60, optimize=True)
            return buf.getvalue()
    except Exception as e:
        logger.debug(f"サムネイル変換エラー {img_path.name}: {e}")
        return None


# ─────────────────────────────────────────────────────
# 公開 API
# ─────────────────────────────────────────────────────

def generate_pdf(dm, session_dir: Path) -> Optional[bytes]:
    """
    DataManager と session_dir から PDF bytes を生成して返す。
    候補・次期候補のみ、件数降順 → 合計価格降順でレイアウト。
    失敗時は None を返す（例外は握り潰す）。
    """
    try:
        return _generate(dm, session_dir)
    except Exception as e:
        logger.error(f"PDF生成エラー: {e}", exc_info=True)
        return None


# ─────────────────────────────────────────────────────
# 内部実装
# ─────────────────────────────────────────────────────

def _generate(dm, session_dir: Path) -> Optional[bytes]:
    try:
        from fpdf import FPDF
    except ImportError:
        logger.error("fpdf2 未インストール。pip install fpdf2 を実行してください。")
        return None

    items = dm.get_all_items()
    if not items:
        return None

    # ── グループ化 ──────────────────────────────────
    group_map: dict = defaultdict(list)
    for item in items:
        gid = item.get("group_id") or item["item_id"]
        group_map[gid].append(item)

    # ── フィルタ・ソート ─────────────────────────────
    groups = []
    for g_items in group_map.values():
        first  = g_items[0]
        status = first.get("status", "waiting")
        if status not in STATUS_TARGET:
            continue
        price  = first.get("price", 0) or 0
        ship   = first.get("shipping", 0) or 0
        total  = first.get("total") or (price + ship)
        thumbs = [
            Path(i["thumbnail_local"])
            for i in g_items
            if i.get("thumbnail_local")
        ][:MAX_IMGS]
        sellers = list({
            i["seller_id"] for i in g_items if i.get("seller_id")
        })
        groups.append({
            "count":    len(g_items),
            "status":   status,
            "title":    (first.get("title_full") or first.get("title_short") or "")[:100],
            "price":    price,
            "shipping": ship,
            "total":    total,
            "sellers":  sellers[:5],
            "thumbs":   thumbs,
        })

    # 件数降順 → 合計価格降順
    groups.sort(key=lambda g: (-g["count"], -g["total"]))

    if not groups:
        logger.info("PDF出力対象なし（候補・次期候補 0グループ）")
        return None

    # ── PDF 初期化 ──────────────────────────────────
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(0, 0, 0)

    font_path = _find_jp_font()
    if font_path:
        pdf.add_font("JP", style="",  fname=font_path)
        pdf.add_font("JP", style="B", fname=font_path)
        fn = "JP"
    else:
        fn = "Helvetica"
        logger.warning("日本語フォントが見つかりません。英数字のみ正常表示されます。")

    progress   = dm.get_progress()
    keyword    = progress.get("keyword", session_dir.name)
    exported   = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    n_cand     = sum(1 for g in groups if g["status"] == "candidate")
    n_next     = sum(1 for g in groups if g["status"] == "next_candidate")
    images_dir = session_dir / "images"

    pdf.add_page()

    # ── 1ページ目ヘッダー ──────────────────────────
    hy = MARGIN
    pdf.set_xy(MARGIN, hy)
    pdf.set_font(fn, style="B", size=12)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(PAGE_W - MARGIN * 2, 7, f"AucFan リサーチ結果  {keyword}", ln=True)
    hy += 7

    pdf.set_xy(MARGIN, hy)
    pdf.set_font(fn, size=8)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(
        PAGE_W - MARGIN * 2, 5,
        f"出力日時: {exported}  |  "
        f"仕入れ候補: {n_cand}件  次期候補: {n_next}件  "
        f"合計: {len(groups)}グループ",
        ln=True,
    )
    hy += 5 + 3   # 3mm スペース

    # ── 2カラムグリッド描画 ────────────────────────
    col_y = [hy, hy]   # 左右カラムの現在 Y 位置
    col   = 0          # 現在カラム (0=左, 1=右)

    for group in groups:
        # カードがページをはみ出すなら、もう一方のカラムへ。両方アウトなら改ページ
        if col_y[col] + CARD_H > PAGE_H - MARGIN:
            other = 1 - col
            if col_y[other] + CARD_H <= PAGE_H - MARGIN:
                col = other
            else:
                pdf.add_page()
                col_y = [MARGIN, MARGIN]
                col   = 0

        cx = MARGIN + col * (COL_W + COL_GAP)
        cy = col_y[col]

        _draw_card(pdf, fn, group, cx, cy, images_dir)

        col_y[col] += CARD_H + CARD_GAP_Y
        col = 1 - col   # 左右交互

    return bytes(pdf.output())


def _draw_card(pdf, fn: str, group: dict, x: float, y: float, images_dir: Path):
    """1枚グループカードを描画する。"""
    w      = COL_W
    status = group["status"]
    bg     = STATUS_BG.get(status, (120, 120, 120))
    lbl    = STATUS_LABEL.get(status, status)

    # ── 外枠 ────────────────────────────────────────
    pdf.set_draw_color(210, 210, 210)
    pdf.set_line_width(0.25)
    pdf.rect(x, y, w, CARD_H)

    # ━━━ [1] ステータスバー ━━━━━━━━━━━━━━━━━━━━━━━━
    pdf.set_fill_color(*bg)
    pdf.rect(x, y, w, STATUS_H, style="F")

    pdf.set_text_color(255, 255, 255)
    pdf.set_font(fn, style="B", size=8)
    pdf.set_xy(x + 2.5, y + 1.5)
    pdf.cell(w * 0.52, 4, lbl)

    pdf.set_font(fn, size=7)
    count_txt = f"同一商品 {group['count']}件"
    pdf.set_xy(x + w * 0.52, y + 1.8)
    pdf.cell(w * 0.46, 3.5, count_txt, align="R")

    # ━━━ [2] 画像ストリップ ━━━━━━━━━━━━━━━━━━━━━━━━
    img_top  = y + STATUS_H + 1.5
    img_size = min((w - 4 - (MAX_IMGS - 1) * 1.0) / MAX_IMGS, IMG_H - 2.5)
    drawn    = 0

    for thumb_path in group["thumbs"]:
        if drawn >= MAX_IMGS:
            break
        full = images_dir / thumb_path.name
        data = _make_thumb(full) if full.exists() else None
        if data:
            ix = x + 2 + drawn * (img_size + 1.0)
            try:
                pdf.image(io.BytesIO(data), x=ix, y=img_top, w=img_size, h=img_size)
                drawn += 1
            except Exception as e:
                logger.debug(f"画像配置エラー: {e}")

    if drawn == 0:
        # プレースホルダー
        pdf.set_fill_color(230, 230, 230)
        pdf.rect(x + 2, img_top, img_size, img_size, style="F")
        pdf.set_text_color(160, 160, 160)
        pdf.set_font(fn, size=6.5)
        pdf.set_xy(x + 2, img_top + img_size / 2 - 2)
        pdf.cell(img_size, 4, "No Image", align="C")

    # ━━━ [3] タイトル ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    title_y = y + STATUS_H + IMG_H
    pdf.set_text_color(30, 30, 30)
    pdf.set_font(fn, size=7.5)
    pdf.set_xy(x + 2, title_y)
    # multi_cell で最大2行に収める
    pdf.multi_cell(w - 4, 4.5, group["title"], max_line_height=4.5)

    # ━━━ [4] 価格行 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    price_y  = y + STATUS_H + IMG_H + TITLE_H
    price    = group["price"]
    ship     = group["shipping"]
    total    = group["total"]
    has_ship = ship > 0

    # 合計 or 価格（大きいフォント）
    pdf.set_font(fn, style="B", size=10)
    pdf.set_text_color(30, 30, 30)
    pdf.set_xy(x + 2, price_y)
    main_price = total if has_ship else price
    pdf.cell(w * 0.48, 5, f"¥{main_price:,}")

    # 内訳（送料あり時のみ）
    if has_ship:
        pdf.set_font(fn, size=6.5)
        pdf.set_text_color(100, 100, 100)
        pdf.set_xy(x + w * 0.48, price_y + 0.5)
        pdf.cell(w * 0.26, 4, f"本体¥{price:,}")
        pdf.set_xy(x + w * 0.74, price_y + 0.5)
        pdf.cell(w * 0.24 - 2, 4, f"送料¥{ship:,}", align="R")

    # 価格ラベル
    pdf.set_font(fn, size=6.5)
    pdf.set_text_color(120, 120, 120)
    pdf.set_xy(x + 2, price_y + 5)
    pdf.cell(w - 4, 3, "合計" if has_ship else "価格（送料込）")

    # ━━━ [5] セラー行 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    seller_y = y + STATUS_H + IMG_H + TITLE_H + PRICE_H
    sellers  = group["sellers"]
    if sellers:
        shown = sellers[:3]
        extra = len(sellers) - len(shown)
        s_txt = "出品者: " + "  ".join(shown)
        if extra > 0:
            s_txt += f"  +{extra}"
    else:
        s_txt = "出品者: —"

    pdf.set_font(fn, size=6.5)
    pdf.set_text_color(110, 110, 110)
    pdf.set_xy(x + 2, seller_y + 1)
    pdf.cell(w - 4, 4, s_txt)
