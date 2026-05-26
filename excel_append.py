"""
excel_append.py — Excel リサーチシート追記モジュール

app.py の /research エンドポイントから呼び出される。
aucfan ツールとは独立して使えるよう、依存を最小限に保つ。

【提供する関数】
  get_excel_info(path)              → Excelの現在状態を返す
  append_amazon(excel_path, data)   → Sheet2/3 にAmazonデータを追記
  download_image(url, save_dir, name) → 画像をローカル保存
"""
from __future__ import annotations

import logging
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# シート名（excel_exporter.py と揃える）
SHEET_OVERVIEW     = "①概要"
SHEET_AMAZON_LIST  = "②Amazonライバル"
SHEET_AMAZON_TEXT  = "③Amazonテキスト"
SHEET_1688_LIST    = "④1688仕入れ"
SHEET_1688_TEXT    = "⑤1688テキスト"

IMAGE_FOLDER_NAME  = "amazon"   # Excelと同フォルダ内の amazon/ サブフォルダ


# ── 画像ダウンロード ────────────────────────────────────────────────────
def download_image(url: str, save_dir: Path, name: str) -> Optional[Path]:
    """画像URLをローカルに保存して Path を返す。失敗時は None。"""
    if not url:
        return None
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
        ext = ".png" if ".png" in url.lower() else ".jpg"
        dest = save_dir / f"{name}{ext}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            dest.write_bytes(resp.read())
        logger.info(f"画像保存: {dest}")
        return dest
    except Exception as e:
        logger.warning(f"画像ダウンロード失敗 ({url}): {e}")
        return None


def ensure_product_folders(excel_path: str) -> dict:
    """
    Excelファイルと同じフォルダに amazon/ と 1688/ サブフォルダを作成する。
    （Excelが商品フォルダ内に置かれていない旧形式でも対応）
    """
    try:
        base = Path(excel_path).parent
        (base / "amazon").mkdir(exist_ok=True)
        (base / "1688").mkdir(exist_ok=True)
        return {"success": True, "base": str(base)}
    except Exception as e:
        logger.warning(f"フォルダ作成エラー: {e}")
        return {"success": False, "error": str(e)}


def download_all_images(image_urls: list, save_dir: Path, asin: str) -> list:
    """
    複数の画像URLを {save_dir}/{asin}/ サブフォルダに 01.jpg, 02.jpg… として保存。
    保存に成功した Path のリストを返す。
    """
    if not image_urls:
        return []
    asin_dir = save_dir / asin
    asin_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, url in enumerate(image_urls, 1):
        if not url:
            continue
        try:
            ext = ".png" if ".png" in url.lower() else ".jpg"
            dest = asin_dir / f"{i:02d}{ext}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                dest.write_bytes(resp.read())
            logger.info(f"画像保存 [{i}]: {dest}")
            saved.append(dest)
        except Exception as e:
            logger.warning(f"画像ダウンロード失敗 [{i}] ({url[:60]}): {e}")
    return saved


# ── Excel情報取得 ───────────────────────────────────────────────────────
def get_excel_info(excel_path: str) -> dict:
    """Excel ファイルの現在の状態を返す。"""
    try:
        from openpyxl import load_workbook
        path = Path(excel_path)
        if not path.exists():
            return {"success": False, "error": f"ファイルが見つかりません: {excel_path}"}

        wb = load_workbook(str(path), read_only=True, data_only=True)
        sheets = list(wb.sheetnames)

        # Sheet1からタイトル取得
        title = ""
        if SHEET_OVERVIEW in sheets:
            ws = wb[SHEET_OVERVIEW]
            val = ws["A1"].value or ""
            title = str(val).replace("リサーチシート　", "").strip()

        # Sheet2の追記件数
        amazon_count = 0
        if SHEET_AMAZON_LIST in sheets:
            ws2 = wb[SHEET_AMAZON_LIST]
            for r in range(4, (ws2.max_row or 3) + 1):
                if ws2.cell(r, 1).value:
                    amazon_count += 1

        wb.close()
        return {
            "success":      True,
            "filename":     path.name,
            "title":        title,
            "sheets":       sheets,
            "amazon_count": amazon_count,
            "is_research":  SHEET_AMAZON_LIST in sheets,
        }
    except Exception as e:
        logger.error(f"Excel情報取得エラー: {e}")
        return {"success": False, "error": str(e)}


# ── Amazon追記 ─────────────────────────────────────────────────────────
def append_amazon(excel_path: str, data: dict) -> dict:
    """
    Sheet2（②Amazonライバル）と Sheet3（③Amazonテキスト）に
    Amazon データを追記して上書き保存する。
    画像は Excelと同じフォルダの _images/ に保存して埋め込む。
    """
    try:
        from openpyxl import load_workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter

        path = Path(excel_path)
        if not path.exists():
            return {"success": False, "error": f"ファイルが見つかりません: {excel_path}"}

        wb = load_workbook(str(path))

        if SHEET_AMAZON_LIST not in wb.sheetnames:
            return {
                "success": False,
                "error": f"シート「{SHEET_AMAZON_LIST}」がありません。"
                         "aucfanアプリのExcelボタンで作成したファイルを指定してください。"
            }

        thin = Side(style="thin", color="BFBFBF")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        # ── Sheet2: ②Amazonライバル ──────────────────────────────
        ws2 = wb[SHEET_AMAZON_LIST]

        # 重複チェック: 同じASINが既に存在する場合はスキップ
        asin_to_add = data.get("asin", "")
        if asin_to_add:
            for r in range(4, (ws2.max_row or 3) + 1):
                if ws2.cell(r, 1).value == asin_to_add:
                    logger.warning(f"重複ASIN スキップ: {asin_to_add} (行{r})")
                    return {
                        "success": False,
                        "duplicate": True,
                        "asin": asin_to_add,
                        "row": r,
                        "error": f"ASIN {asin_to_add} は既に{r}行目に追記済みです。",
                    }

        # 4行目以降で最初の空行を探す
        next_row = 4
        for r in range(4, (ws2.max_row or 3) + 2):
            if ws2.cell(r, 1).value is None:
                next_row = r
                break

        ws2.row_dimensions[next_row].height = 90

        input_url = data.get("input_url", "") or ""
        resolved_url = data.get("url", "") or ""

        row_values = [
            data.get("asin", ""),
            data.get("title", ""),
            data.get("price", ""),
            data.get("rating", ""),
            data.get("review_count", ""),
            "あり" if data.get("has_aplus") else "なし",
            resolved_url,
            input_url,   # 入力URL（短縮URLそのまま）
            "",          # 画像列（後で埋め込み）
        ]
        for col, val in enumerate(row_values, 1):
            c = ws2.cell(next_row, col)
            c.value = val
            c.font = Font(name="BIZ UDGothic")
            c.border = border
            c.alignment = Alignment(
                vertical="center",
                wrap_text=(col == 2),
                horizontal="left" if col in (2, 7, 8) else "center"
            )

        # ── フォルダ確認（amazon/ 1688/ が存在しない旧形式にも対応） ──
        ensure_product_folders(str(path))

        # ── 画像ダウンロード & 埋め込み ──────────────────────────
        image_saved = False
        image_path = None
        img_dir = path.parent / IMAGE_FOLDER_NAME   # amazon/
        safe_asin = re.sub(r'[^\w]', '_', data.get("asin", "img"))

        # メイン画像（Excelに埋め込む用）
        if data.get("image_url"):
            image_path = download_image(data["image_url"], img_dir, safe_asin)

        # 全画像（カタログ参考用） → _images/{ASIN}/ サブフォルダに保存
        all_image_paths = []
        if data.get("image_urls"):
            all_image_paths = download_all_images(
                data["image_urls"], img_dir, safe_asin
            )
            logger.info(f"全画像保存完了: {len(all_image_paths)}枚 → {img_dir / safe_asin}")

        tmp_dir = tempfile.mkdtemp()
        try:
            if image_path and image_path.exists():
                try:
                    from PIL import Image as PILImage
                    img = PILImage.open(image_path).convert("RGBA")
                    img.thumbnail((100, 85), PILImage.LANCZOS)
                    bg = PILImage.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[3])
                    thumb = Path(tmp_dir) / image_path.name
                    bg.save(str(thumb), "JPEG", quality=85)

                    from openpyxl.drawing.image import Image as XLImage
                    xl_img = XLImage(str(thumb))
                    xl_img.anchor = f"I{next_row}"
                    ws2.add_image(xl_img)
                    ws2.cell(next_row, 9).value = None
                    image_saved = True
                except Exception as e:
                    logger.warning(f"画像埋め込みエラー: {e}")
                    ws2.cell(next_row, 9).value = data.get("image_url", "")

            # ── Sheet3: ③Amazonテキスト ──────────────────────────
            if SHEET_AMAZON_TEXT in wb.sheetnames:
                ws3 = wb[SHEET_AMAZON_TEXT]
                cur_max = ws3.max_row or 2
                start = cur_max + 2 if cur_max > 2 else 4

                def _write(r, label, value):
                    height = max(18, min(150, len(str(value)) // 4 + 18))
                    ws3.row_dimensions[r].height = height
                    c_label = ws3.cell(r, 1)
                    c_label.value = label
                    c_label.font = Font(name="BIZ UDGothic", bold=True)
                    c_label.fill = PatternFill("solid", fgColor="E2EFDA")
                    c_label.border = border
                    c_val = ws3.cell(r, 2)
                    c_val.value = value
                    c_val.font = Font(name="BIZ UDGothic")
                    c_val.alignment = Alignment(vertical="top", wrap_text=True)
                    c_val.border = border

                # セパレーター
                ws3.row_dimensions[start - 1].height = 6
                ws3.merge_cells(f"A{start}:B{start}")
                sep = ws3.cell(start, 1)
                sep.value = f"── {data.get('asin', '')}  {data.get('title', '')[:50]} ──"
                sep.font = Font(name="BIZ UDGothic", bold=True, color="FFFFFF")
                sep.fill = PatternFill("solid", fgColor="375623")
                sep.alignment = Alignment(horizontal="left", vertical="center")
                ws3.row_dimensions[start].height = 22

                _write(start + 1, "タイトル",   data.get("title", ""))
                _write(start + 2, "価格",        data.get("price", ""))
                _write(start + 3, "商品の特徴",  "\n".join(data.get("bullets", [])))
                _write(start + 4, "商品説明",    data.get("description", ""))
                specs_text = "\n".join(
                    f"{k}: {v}" for k, v in (data.get("specs") or {}).items()
                )
                _write(start + 5, "仕様・詳細",  specs_text)

            # 保存（tmpフォルダ削除前に必ず実行）
            wb.save(str(path))

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return {
            "success":     True,
            "row":         next_row,
            "asin":        data.get("asin", ""),
            "title":       data.get("title", ""),
            "price":       data.get("price", ""),
            "has_image":   image_saved,
            "image_count": len(all_image_paths),  # 保存した全画像枚数
        }

    except Exception as e:
        logger.error(f"Excel追記エラー: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
