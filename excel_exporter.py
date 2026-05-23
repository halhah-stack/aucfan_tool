"""
excel_exporter.py — AucFan リサーチシート Excel エクスポーター

Webアプリの「Excelエクスポート」ボタンから呼ばれる。
  対象  : ng 以外の全グループ（group_size >= MIN_COUNT）
  ソート : 件数（group_size）降順
  出力  : openpyxl で Excel bytes を返す（app.py でダウンロードとして送信）
"""
from __future__ import annotations

import io
import logging
import shutil
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

# ── フィルター設定 ─────────────────────────────────────────────────────
MIN_COUNT   = 4           # 件数の最小値（4件以上）
SKIP_STATUS = {"ng"}      # 除外するステータス

# ── スタイル定数 ──────────────────────────────────────────────────────
FONT    = "BIZ UDGothic"
SZ      = 11

HDR_BG  = "1F4E79"   # タイトルバー（紺）
HDR_FG  = "FFFFFF"
SUB_BG  = "2E75B6"   # 列ヘッダー（青）
SUB_FG  = "FFFFFF"
LBL_BG  = "D6E4F0"   # ラベル（薄青）
INP_BG  = "FFF9C4"   # 手入力セル（黄）
FML_BG  = "E8F5E9"   # 自動計算セル（緑）
IMG_BG  = "F0F0F0"   # 画像エリア（薄灰）
ALT_BG  = "F8FBFF"   # 偶数行（薄青白）

DATA_START = 6

# 画像リサイズ上限（ピクセル）
THUMB_MAX_W = 110
THUMB_MAX_H = 90


# ── スタイルヘルパー ────────────────────────────────────────────────────
def _fnt(bold=False, size=SZ, color="000000"):
    return Font(name=FONT, size=size, bold=bold, color=color)

def _fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def _aln(h="left", v="center", wrap=False):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

def _bdr():
    s = Side(style="thin", color="CCCCCC")
    return Border(left=s, right=s, top=s, bottom=s)

def _sc(ws, row, col, value=None, font=None, fill=None,
        align=None, border=None, fmt=None):
    c = ws.cell(row=row, column=col)
    if value  is not None: c.value  = value
    if font:               c.font   = font
    if fill:               c.fill   = fill
    if align:              c.alignment = align
    if border:             c.border = border
    if fmt:                c.number_format = fmt
    return c


# ── 画像リサイズ ────────────────────────────────────────────────────────
def _make_thumb(src_path: Path, tmp_dir: str) -> Optional[str]:
    """PIL でリサイズし、tmpディレクトリに保存したパスを返す。失敗時 None。"""
    try:
        from PIL import Image as PILImage
        img = PILImage.open(src_path).convert("RGBA")
        img.thumbnail((THUMB_MAX_W, THUMB_MAX_H), PILImage.LANCZOS)
        bg = PILImage.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        out_path = str(Path(tmp_dir) / src_path.name)
        bg.save(out_path, "JPEG", quality=85)
        return out_path
    except Exception as e:
        logger.debug(f"画像処理スキップ ({src_path.name}): {e}")
        return None


# ── DataManager からグループリストを生成 ────────────────────────────────
def _build_groups(dm) -> list[dict]:
    """
    DataManager からアイテムを取得し、4件以上のグループを件数降順で返す。
    各グループ dict:
      title, group_size, min_total, sellers, url, thumb_path
    """
    items = dm.get_all_items()
    if not items:
        return []

    # group_id でまとめる
    group_map: dict = defaultdict(list)
    for item in items:
        gid = item.get("group_id") or item.get("item_id")
        group_map[gid].append(item)

    result = []
    for gid, g_items in group_map.items():
        # 代表行 = group_id == item_id の行（なければ先頭）
        rep = next(
            (i for i in g_items if i.get("item_id") == gid),
            g_items[0]
        )

        status = rep.get("status", "")
        if status in SKIP_STATUS:
            continue

        group_size = int(rep.get("group_size") or 0)
        if group_size < MIN_COUNT:
            continue

        # 最安値（グループ内 total の最小値）
        totals = [
            float(i.get("total") or 0)
            for i in g_items
            if float(i.get("total") or 0) > 0
        ]
        min_total = int(min(totals)) if totals else 0

        # セラーID（重複除去、最大3個）
        sellers: list[str] = []
        seen: set[str] = set()
        for i in g_items:
            sid = (i.get("seller_id") or "").strip()
            if sid and sid not in seen:
                seen.add(sid)
                sellers.append(sid)
            if len(sellers) >= 3:
                break

        # URL（代表行）
        url = rep.get("url", "") or ""

        # サムネイルパス（thumbnail_local = Macのローカルパス）
        thumb_path: Optional[Path] = None
        th = rep.get("thumbnail_local", "") or ""
        if th:
            p = Path(th)
            if p.exists():
                thumb_path = p

        result.append({
            "title":      rep.get("title_short") or rep.get("title_full") or "",
            "group_size": group_size,
            "min_total":  min_total,
            "sellers":    sellers,
            "url":        url,
            "thumb_path": thumb_path,
        })

    # 件数降順ソート
    result.sort(key=lambda x: -x["group_size"])
    return result


# ── Excel ワークブック生成 ──────────────────────────────────────────────
def _build_workbook(groups: list[dict], session_name: str,
                    research_date: datetime, embed_images: bool) -> openpyxl.Workbook:
    data_rows = max(len(groups), 10)
    end_row   = DATA_START + data_rows - 1

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "①Aucfan"

    # ── 列幅 ──
    col_widths = [4, 16, 11, 42, 12, 9, 16, 18, 18, 18, 38, 22]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ── Row 1: タイトルバー ──
    ws.row_dimensions[1].height = 26
    ws.merge_cells("A1:L1")
    c = ws["A1"]
    c.value     = f"Aucfan リサーチシート  ―  {session_name}"
    c.font      = Font(name=FONT, size=13, bold=True, color=HDR_FG)
    c.fill      = _fill(HDR_BG)
    c.alignment = _aln("center", "center")

    # ── Row 2: サマリー行 ──
    ws.row_dimensions[2].height = 22
    _sc(ws, 2, 1, "調査商品数",
        font=_fnt(bold=True), fill=_fill(LBL_BG),
        align=_aln("center","center"), border=_bdr())
    _sc(ws, 2, 2, f"=COUNTA(D{DATA_START}:D{end_row})",
        font=_fnt(bold=True), fill=_fill(FML_BG),
        align=_aln("center","center"), border=_bdr())
    _sc(ws, 2, 3, "4件以上の商品",
        font=_fnt(bold=True), fill=_fill(LBL_BG),
        align=_aln("center","center"), border=_bdr())
    _sc(ws, 2, 4, f'=COUNTIF(E{DATA_START}:E{end_row},">=4")',
        font=_fnt(bold=True), fill=_fill(FML_BG),
        align=_aln("center","center"), border=_bdr())
    _sc(ws, 2, 5, "セッション",
        font=_fnt(bold=True), fill=_fill(LBL_BG),
        align=_aln("center","center"), border=_bdr())
    ws.merge_cells("F2:L2")
    _sc(ws, 2, 6, session_name,
        font=Font(name=FONT, size=10, color="444444"),
        fill=_fill(INP_BG), align=_aln("left","center"), border=_bdr())

    # ── Row 3: 凡例 ──
    ws.row_dimensions[3].height = 18
    ws.merge_cells("A3:L3")
    c = ws["A3"]
    c.value     = (f"  ■ 黄色 = 手入力セル　　■ 緑色 = 自動計算セル"
                   f"　　（エクスポート: {research_date.strftime('%Y/%m/%d')}）")
    c.font      = Font(name=FONT, size=10, color="555555")
    c.fill      = _fill("FAFAFA")
    c.alignment = _aln("left", "center")

    # ── Row 4: スペーサー ──
    ws.row_dimensions[4].height = 4

    # ── Row 5: 列ヘッダー ──
    ws.row_dimensions[5].height = 34
    headers = [
        "No", "画像", "日付", "代表キーワード",
        "件数\n（直近30日）", "4件\n以上",
        "最安値\n（価格＋送料）",
        "セラーID①", "セラーID②", "セラーID③",
        "検索URL\n（Aucfan）", "備考"
    ]
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=5, column=col)
        c.value     = h
        c.font      = Font(name=FONT, size=SZ, bold=True, color=SUB_FG)
        c.fill      = _fill(SUB_BG)
        c.alignment = _aln("center", "center", wrap=True)
        c.border    = _bdr()

    ws.freeze_panes = "A6"

    # ── データ行 ──
    tmp_dir = tempfile.mkdtemp()
    try:
        for i in range(data_rows):
            r    = DATA_START + i
            grp  = groups[i] if i < len(groups) else None
            row_bg = "FFFFFF" if i % 2 == 0 else ALT_BG
            ws.row_dimensions[r].height = 72

            # A: No
            _sc(ws, r, 1, i + 1,
                font=_fnt(), fill=_fill(row_bg),
                align=_aln("center","center"), border=_bdr())

            # B: 画像
            img_cell = ws.cell(row=r, column=2)
            img_cell.fill      = _fill(IMG_BG)
            img_cell.alignment = _aln("center", "center", wrap=True)
            img_cell.border    = _bdr()

            if grp and grp["thumb_path"] and embed_images:
                thumb_file = _make_thumb(grp["thumb_path"], tmp_dir)
                if thumb_file:
                    try:
                        from openpyxl.drawing.image import Image as XLImage
                        xl_img = XLImage(thumb_file)
                        xl_img.anchor = f"B{r}"
                        ws.add_image(xl_img)
                        img_cell.value = None
                    except Exception as e:
                        logger.warning(f"画像埋め込みエラー 行{r}: {e}")
                        img_cell.value = "画像\nエラー"
                        img_cell.font  = Font(name=FONT, size=9, color="CC0000")
                else:
                    img_cell.value = "画像\nここに貼付"
                    img_cell.font  = Font(name=FONT, size=9, color="AAAAAA")
            else:
                img_cell.value = "画像\nここに貼付"
                img_cell.font  = Font(name=FONT, size=9, color="AAAAAA")

            # C: 日付
            _sc(ws, r, 3,
                value=research_date if grp else None,
                font=_fnt(), fill=_fill(INP_BG if grp else row_bg),
                align=_aln("center","center"), border=_bdr(),
                fmt="YYYY/MM/DD")

            # D: 代表キーワード
            _sc(ws, r, 4,
                value=grp["title"] if grp else None,
                font=_fnt(), fill=_fill(INP_BG if grp else row_bg),
                align=_aln("left","center", wrap=True), border=_bdr())

            # E: 件数（group_size）
            _sc(ws, r, 5,
                value=grp["group_size"] if grp else None,
                font=_fnt(), fill=_fill(FML_BG if grp else row_bg),
                align=_aln("center","center"), border=_bdr(),
                fmt="#,##0")

            # F: 4件以上（自動判定）
            _sc(ws, r, 6,
                value=f'=IF(E{r}="","",IF(E{r}>=4,"✓","✗"))',
                font=_fnt(bold=True), fill=_fill(FML_BG),
                align=_aln("center","center"), border=_bdr())

            # G: 最安値
            _sc(ws, r, 7,
                value=grp["min_total"] if (grp and grp["min_total"]) else None,
                font=_fnt(), fill=_fill(FML_BG if grp else row_bg),
                align=_aln("right","center"), border=_bdr(),
                fmt="#,##0")

            # H〜J: セラーID①②③
            for col_idx, col_num in enumerate([8, 9, 10]):
                sellers = grp["sellers"] if grp else []
                val = sellers[col_idx] if col_idx < len(sellers) else None
                _sc(ws, r, col_num,
                    value=val,
                    font=_fnt(), fill=_fill(INP_BG if val else row_bg),
                    align=_aln("left","center"), border=_bdr())

            # K: 検索URL
            _sc(ws, r, 11,
                value=grp["url"] if grp else None,
                font=_fnt(), fill=_fill(INP_BG if grp else row_bg),
                align=_aln("left","center"), border=_bdr())

            # L: 備考（手入力）
            _sc(ws, r, 12,
                font=_fnt(), fill=_fill(INP_BG),
                align=_aln("left","center", wrap=True), border=_bdr())

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return wb


# ── 公開 API ───────────────────────────────────────────────────────────
def generate_excel(dm, session_name: str, embed_images: bool = True) -> Optional[bytes]:
    """
    DataManager からリサーチシート Excel を生成し bytes で返す。
    失敗時は None を返す。

    Args:
        dm            : DataManager インスタンス
        session_name  : セッション名（ファイル名・タイトル用）
        embed_images  : True なら thumbnail_local の画像を埋め込む
    """
    try:
        groups = _build_groups(dm)
        if not groups:
            logger.info("Excel出力対象なし（4件以上グループ 0件）")
            return None

        research_date = datetime.now()

        wb = _build_workbook(groups, session_name, research_date, embed_images)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        logger.info(
            f"Excel生成完了: {session_name} / {len(groups)}商品"
            + (f" 画像あり" if embed_images else "")
        )
        return buf.read()

    except Exception as e:
        logger.error(f"Excel生成エラー: {e}", exc_info=True)
        return None
