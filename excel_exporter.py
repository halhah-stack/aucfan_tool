"""
excel_exporter.py — Aucfan リサーチシート Excel エクスポーター

リサーチ_テンプレート.xlsx を読み込んでデータを流し込み、
商品タイトル_リサーチ.xlsx として保存する。

書式変更は リサーチ_テンプレート.xlsx を直接編集するだけでOK。
コードは「どのセルに何を書くか」だけ担当する。
"""
from __future__ import annotations

import io
import logging
import re
import shutil
import tempfile
from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl import load_workbook
from openpyxl.styles import Font

logger = logging.getLogger(__name__)

# ── 定数 ──────────────────────────────────────────────────────────────
TEMPLATE_PATH = Path(__file__).parent / "リサーチ_テンプレート.xlsx"
DATA_ROW      = 6       # テンプレートのデータ行番号
THUMB_MAX_W   = 110     # 画像リサイズ上限（px）
THUMB_MAX_H   = 90

FONT_NAME = "BIZ UDGothic"


# ── ファイル名サニタイズ ────────────────────────────────────────────────
def sanitize_filename(title: str, max_len: int = 60) -> str:
    title = re.sub(r'[\\/:*?"<>|]', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title[:max_len] if title else "リサーチ"


# ── 画像リサイズ ────────────────────────────────────────────────────────
def _make_thumb(src_path: Path, tmp_dir: str) -> Optional[str]:
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


# ── テンプレートにデータを流し込む ────────────────────────────────────
def _fill_sheet(ws, group: dict, session_name: str, row: int = DATA_ROW):
    """
    ワークシートの指定行にグループデータを書き込む。
    テンプレートの書式はそのまま維持し、値だけ設定する。
    """
    now = datetime.now()

    # Row 1: タイトル（セッション名を付記）
    ws["A1"].value = f"Aucfan リサーチシート  ―  {session_name}"

    # Row 2: セッション名（F2セル）
    ws.cell(2, 6).value = f"{session_name}  （{now.strftime('%Y/%m/%d')}）"

    # Row 2: サマリー数式を実際の行番号に合わせる
    ws.cell(2, 2).value = f"=COUNTA(D{row}:D{row})"
    ws.cell(2, 4).value = f'=COUNTIF(E{row}:E{row},">=4")'

    # データ行
    ws.cell(row, 1).value = 1                          # No
    ws.cell(row, 3).value = now                        # 日付
    ws.cell(row, 4).value = group["title"]             # 代表キーワード
    ws.cell(row, 5).value = group["group_size"]        # 件数
    ws.cell(row, 6).value = (                          # 4件以上（数式）
        f'=IF(E{row}="","",IF(E{row}>=4,"✓","✗"))'
    )
    if group["min_total"]:
        ws.cell(row, 7).value = group["min_total"]     # 最安値

    sellers = group.get("sellers", [])
    for i, col in enumerate([8, 9, 10]):               # セラーID①②③
        ws.cell(row, col).value = sellers[i] if i < len(sellers) else None

    ws.cell(row, 11).value = group.get("url", "")     # 検索URL


# ── グループ情報を DataManager から取得 ────────────────────────────────
def _get_group(dm, group_id: str, session_name: str = "") -> Optional[dict]:
    all_items = dm.get_all_items()
    g_items = [i for i in all_items
               if (i.get("group_id") or i.get("item_id")) == group_id]
    if not g_items:
        return None

    rep = next((i for i in g_items if i.get("item_id") == group_id), g_items[0])

    totals = [float(i.get("total") or 0) for i in g_items if float(i.get("total") or 0) > 0]

    sellers: list[str] = []
    seen: set[str] = set()
    for i in g_items:
        sid = (i.get("seller_id") or "").strip()
        if sid and sid not in seen:
            seen.add(sid)
            sellers.append(sid)
        if len(sellers) >= 3:
            break

    thumb_path: Optional[Path] = None
    th = rep.get("thumbnail_local", "") or ""
    if th:
        p = Path(th)
        if p.exists():
            # ① 記録されたパスがそのまま存在する（十王Macまたは同一Mac）
            thumb_path = p
        elif session_name:
            # ② パスが存在しない場合（守谷Macなど別環境）:
            #    ファイル名だけ取り出して config.LOCAL_IMAGE_CACHE_DIR で探す
            #    （GDriveミラーリング済みフォルダ: リサーチ結果/セッション名/images/）
            try:
                import config
                fallback = (
                    Path(config.LOCAL_IMAGE_CACHE_DIR)
                    / session_name / "images" / Path(th).name
                )
                if fallback.exists():
                    thumb_path = fallback
                    logger.debug(f"画像をGDriveミラーから使用: {fallback}")
                else:
                    logger.debug(f"画像が見つかりません（ローカル・GDriveミラーともに不在）: {Path(th).name}")
            except Exception as e:
                logger.debug(f"フォールバックパス解決エラー: {e}")

    return {
        "title":      rep.get("title_short") or rep.get("title_full") or "",
        "group_size": int(rep.get("group_size") or len(g_items)),
        "min_total":  int(min(totals)) if totals else 0,
        "sellers":    sellers,
        "url":        rep.get("url", "") or "",
        "thumb_path": thumb_path,
    }


# ── 公開 API ───────────────────────────────────────────────────────────
def generate_excel_single(dm, group_id: str,
                          embed_images: bool = True) -> Optional[tuple[bytes, str]]:
    """
    指定した group_id 1件分の Excel を生成し (bytes, filename) を返す。
    失敗時は None を返す。
    """
    if not TEMPLATE_PATH.exists():
        logger.error(f"テンプレートが見つかりません: {TEMPLATE_PATH}")
        logger.error("build_template.py を実行してテンプレートを生成してください。")
        return None

    try:
        group = _get_group(dm, group_id)
        if not group:
            logger.warning(f"グループが見つかりません: {group_id}")
            return None

        session_name = group_id  # フォールバック

        # テンプレートを読み込む（書式はテンプレートのまま）
        wb = load_workbook(str(TEMPLATE_PATH))
        ws = wb.active

        # データを流し込む
        _fill_sheet(ws, group, session_name, row=DATA_ROW)

        # 画像埋め込み
        tmp_dir = tempfile.mkdtemp()
        try:
            img_cell = ws.cell(DATA_ROW, 2)
            if group["thumb_path"] and embed_images:
                thumb_file = _make_thumb(group["thumb_path"], tmp_dir)
                if thumb_file:
                    try:
                        from openpyxl.drawing.image import Image as XLImage
                        xl_img = XLImage(thumb_file)
                        xl_img.anchor = f"B{DATA_ROW}"
                        ws.add_image(xl_img)
                        img_cell.value = None
                    except Exception as e:
                        logger.warning(f"画像埋め込みエラー: {e}")

            # ★ wb.save() は tmpフォルダを削除する前に実行する
            #   （openpyxlは save() 時に画像ファイルを再読みするため）
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        filename = f"{sanitize_filename(group['title'])}_リサーチ.xlsx"
        logger.info(f"Excel生成完了: {filename}")
        return buf.read(), filename

    except Exception as e:
        logger.error(f"Excel生成エラー: {e}", exc_info=True)
        return None


def generate_excel_single_with_session(dm, group_id: str, session_name: str,
                                       embed_images: bool = True) -> Optional[tuple[bytes, str]]:
    """session_name を明示的に渡すバージョン。"""
    if not TEMPLATE_PATH.exists():
        logger.error(f"テンプレートが見つかりません: {TEMPLATE_PATH}")
        return None

    try:
        group = _get_group(dm, group_id, session_name)
        if not group:
            return None

        wb = load_workbook(str(TEMPLATE_PATH))
        ws = wb.active
        _fill_sheet(ws, group, session_name, row=DATA_ROW)

        tmp_dir = tempfile.mkdtemp()
        try:
            img_cell = ws.cell(DATA_ROW, 2)
            if group["thumb_path"] and embed_images:
                thumb_file = _make_thumb(group["thumb_path"], tmp_dir)
                if thumb_file:
                    try:
                        from openpyxl.drawing.image import Image as XLImage
                        xl_img = XLImage(thumb_file)
                        xl_img.anchor = f"B{DATA_ROW}"
                        ws.add_image(xl_img)
                        img_cell.value = None
                    except Exception as e:
                        logger.warning(f"画像埋め込みエラー: {e}")

            # ★ wb.save() は tmpフォルダを削除する前に実行する
            #   （openpyxlは save() 時に画像ファイルを再読みするため）
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        filename = f"{sanitize_filename(group['title'])}_リサーチ.xlsx"
        logger.info(f"Excel生成完了: {filename} (session={session_name})")
        return buf.read(), filename

    except Exception as e:
        logger.error(f"Excel生成エラー: {e}", exc_info=True)
        return None
