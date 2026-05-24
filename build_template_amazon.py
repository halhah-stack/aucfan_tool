"""
build_template_amazon.py — AucFan + Amazon 統合リサーチシート テンプレート生成（A案）

AucFan列（A〜L）の右側に Amazon ライバルリサーチ列（M〜W）を追加した
横並び統合テンプレートを生成する。

元のテンプレート（リサーチ_テンプレート.xlsx）はそのまま残るため、
いつでも元に戻せる。

実行方法:
  cd ~/Downloads/aucfan_tool
  python3 build_template_amazon.py

出力ファイル: リサーチ_テンプレート_Amazon.xlsx
"""

from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ── 出力先（元テンプレートとは別ファイル） ────────────────────────────
OUT_PATH = Path(__file__).parent / "リサーチ_テンプレート_Amazon.xlsx"

# ── スタイル定数（元テンプレートと共通） ─────────────────────────────
FONT_NAME = "BIZ UDGothic"
FONT_SIZE = 11

HDR_BG = "1F4E79"   # タイトルバー（紺）
HDR_FG = "FFFFFF"
SUB_BG = "2E75B6"   # AucFan列ヘッダー（青）
SUB_FG = "FFFFFF"
AMZ_BG = "375623"   # Amazon列ヘッダー（緑）
AMZ_FG = "FFFFFF"
LBL_BG = "D6E4F0"   # ラベル（薄青）
INP_BG = "FFF9C4"   # 手入力セル（黄）
FML_BG = "E8F5E9"   # 自動計算セル（薄緑）
IMG_BG = "F0F0F0"   # 画像エリア（薄灰）
AMZ_INP = "FFF3E0"  # Amazon手入力セル（薄橙）
AMZ_FML = "E8F5E9"  # Amazon自動計算セル（薄緑）

DATA_ROW = 6        # データ行

# 為替レート（円/元）- セルW2に設定し、利益計算で参照
EXCHANGE_RATE_DEFAULT = 22  # デフォルト22円/元

# ── 列定義: (列記号, 幅, ヘッダーテキスト, 背景色, 書式, グループ) ──
# グループ: "aucfan" or "amazon"
COLUMNS = [
    # ── AucFan列（元テンプレートと同じ）──────────────────────────────
    ("A",  4,  "No",                     None,    None,         "aucfan"),
    ("B",  16, "画像",                   IMG_BG,  None,         "aucfan"),
    ("C",  11, "日付",                   INP_BG,  "YYYY/MM/DD", "aucfan"),
    ("D",  42, "代表キーワード",         INP_BG,  None,         "aucfan"),
    ("E",  12, "件数\n（直近30日）",    FML_BG,  "#,##0",      "aucfan"),
    ("F",  9,  "4件\n以上",             FML_BG,  None,         "aucfan"),
    ("G",  16, "最安値\n（価格＋送料）", FML_BG, "#,##0",      "aucfan"),
    ("H",  18, "セラーID①",             INP_BG,  None,         "aucfan"),
    ("I",  18, "セラーID②",             INP_BG,  None,         "aucfan"),
    ("J",  18, "セラーID③",             INP_BG,  None,         "aucfan"),
    ("K",  38, "検索URL\n（Aucfan）",   INP_BG,  None,         "aucfan"),
    ("L",  22, "備考",                   INP_BG,  None,         "aucfan"),
    # ── Amazon列（新規追加）─────────────────────────────────────────
    ("M",  12, "ライバル\n件数",         AMZ_INP, "#,##0",      "amazon"),
    ("N",  14, "Amazon\n最安値",         AMZ_INP, "#,##0",      "amazon"),
    ("O",  14, "Amazon\n最高値",         AMZ_INP, "#,##0",      "amazon"),
    ("P",  14, "1688\n仕入値（元）",    AMZ_INP, "#,##0.00",   "amazon"),
    ("Q",  14, "仕入値（円）\n自動計算", AMZ_FML, "#,##0",      "amazon"),
    ("R",  14, "Amazon\n販売予定価格",   AMZ_INP, "#,##0",      "amazon"),
    ("S",  14, "FBA\n手数料",            AMZ_INP, "#,##0",      "amazon"),
    ("T",  14, "利益\n自動計算",         AMZ_FML, "#,##0",      "amazon"),
    ("U",  10, "利益率\n自動計算",       AMZ_FML, "0.0%",       "amazon"),
    ("V",  38, "Amazon\n検索URL",        AMZ_INP, None,         "amazon"),
    ("W",  22, "Amazonメモ",             AMZ_INP, None,         "amazon"),
]

TOTAL_COLS = len(COLUMNS)
LAST_COL   = COLUMNS[-1][0]  # "W"


# ── ヘルパー ──────────────────────────────────────────────────────────
def fnt(bold=False, size=FONT_SIZE, color="000000"):
    return Font(name=FONT_NAME, size=size, bold=bold, color=color)

def fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def aln(h="left", v="center", wrap=False):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

def bdr(color="CCCCCC"):
    s = Side(style="thin", color=color)
    return Border(left=s, right=s, top=s, bottom=s)

def cell(ws, row, col, value=None, font=None, bg=None,
         align=None, border=None, fmt=None):
    c = ws.cell(row=row, column=col)
    if value  is not None: c.value  = value
    if font:               c.font   = font
    if bg:                 c.fill   = fill(bg)
    if align:              c.alignment = align
    if border:             c.border = border
    if fmt:                c.number_format = fmt
    return c


# ── ワークブック生成 ──────────────────────────────────────────────────
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "①リサーチ"

# 列幅
for col_letter, width, *_ in COLUMNS:
    ws.column_dimensions[col_letter].width = width


# ── Row 1: タイトルバー ──────────────────────────────────────────────
ws.row_dimensions[1].height = 26
ws.merge_cells(f"A1:{LAST_COL}1")
c = ws["A1"]
c.value     = "Aucfan + Amazon 統合リサーチシート"
c.font      = Font(name=FONT_NAME, size=13, bold=True, color=HDR_FG)
c.fill      = fill(HDR_BG)
c.alignment = aln("center", "center")


# ── Row 2: サマリー行 ────────────────────────────────────────────────
ws.row_dimensions[2].height = 22

# 調査商品数
cell(ws, 2, 1, "調査商品数",
     font=fnt(bold=True), bg=LBL_BG, align=aln("center","center"), border=bdr())
cell(ws, 2, 2, f"=COUNTA(D{DATA_ROW}:D{DATA_ROW})",
     font=fnt(bold=True), bg=FML_BG, align=aln("center","center"), border=bdr())

# 4件以上
cell(ws, 2, 3, "4件以上の商品",
     font=fnt(bold=True), bg=LBL_BG, align=aln("center","center"), border=bdr())
cell(ws, 2, 4, f'=COUNTIF(E{DATA_ROW}:E{DATA_ROW},">=4")',
     font=fnt(bold=True), bg=FML_BG, align=aln("center","center"), border=bdr())

# セッション名
cell(ws, 2, 5, "セッション",
     font=fnt(bold=True), bg=LBL_BG, align=aln("center","center"), border=bdr())
ws.merge_cells("F2:L2")
cell(ws, 2, 6, "",
     font=Font(name=FONT_NAME, size=10, color="444444"),
     bg=INP_BG, align=aln("left","center"), border=bdr())

# 為替レート設定欄（Amazon計算に使用）
cell(ws, 2, 13, "為替レート（円/元）",
     font=fnt(bold=True), bg="FFF3E0", align=aln("center","center"), border=bdr())
ws.merge_cells("N2:O2")
c_rate = ws.cell(row=2, column=14)
c_rate.value          = EXCHANGE_RATE_DEFAULT
c_rate.font           = fnt(bold=True)
c_rate.fill           = fill(AMZ_FML)
c_rate.alignment      = aln("center", "center")
c_rate.border         = bdr()
c_rate.number_format  = "#,##0.00"
# セルN2に名前をつけてP列から参照できるようにする（通常のExcel数式で参照）
# → $N$2 で参照する

# スペーサー
ws.merge_cells(f"P2:{LAST_COL}2")
cell(ws, 2, 16, "← 為替レートをN2に入力してください",
     font=Font(name=FONT_NAME, size=9, color="888888"),
     bg="FFFBF5", align=aln("left","center"), border=bdr())


# ── Row 3: 凡例 ──────────────────────────────────────────────────────
ws.row_dimensions[3].height = 18
ws.merge_cells(f"A3:{LAST_COL}3")
c = ws["A3"]
c.value = (
    "  ■ 黄色 = 手入力セル（AucFan）　"
    "■ 橙色 = 手入力セル（Amazon）　"
    "■ 緑色 = 自動計算セル"
)
c.font      = Font(name=FONT_NAME, size=10, color="555555")
c.fill      = fill("FAFAFA")
c.alignment = aln("left", "center")


# ── Row 4: スペーサー ─────────────────────────────────────────────────
ws.row_dimensions[4].height = 4


# ── Row 5: 列ヘッダー ────────────────────────────────────────────────
ws.row_dimensions[5].height = 40
for col_idx, (_, _, header, _, _, group) in enumerate(COLUMNS, 1):
    c = ws.cell(row=5, column=col_idx)
    c.value     = header
    c.font      = Font(name=FONT_NAME, size=FONT_SIZE, bold=True,
                       color=SUB_FG if group == "aucfan" else AMZ_FG)
    c.fill      = fill(SUB_BG if group == "aucfan" else AMZ_BG)
    c.alignment = aln("center", "center", wrap=True)
    c.border    = bdr()


ws.freeze_panes = "A6"


# ── Row 6: データ行テンプレート ───────────────────────────────────────
ws.row_dimensions[DATA_ROW].height = 72

for col_idx, (col_letter, _, _, bg_color, fmt_str, group) in enumerate(COLUMNS, 1):
    c = ws.cell(row=DATA_ROW, column=col_idx)
    c.font      = fnt()
    c.alignment = aln("left", "center", wrap=(col_letter in ["D", "L", "W"]))
    c.border    = bdr()
    if bg_color:
        c.fill = fill(bg_color)
    if fmt_str:
        c.number_format = fmt_str

# ── AucFan側のセル個別設定（元テンプレートと同じ）──────────────────
# No
ws.cell(DATA_ROW, 1).alignment = aln("center", "center")
# 日付
ws.cell(DATA_ROW, 3).alignment = aln("center", "center")
# 件数
ws.cell(DATA_ROW, 5).alignment = aln("center", "center")
# 4件以上（数式プレースホルダー）
ws.cell(DATA_ROW, 6).value     = f'=IF(E{DATA_ROW}="","",IF(E{DATA_ROW}>=4,"✓","✗"))'
ws.cell(DATA_ROW, 6).font      = fnt(bold=True)
ws.cell(DATA_ROW, 6).alignment = aln("center", "center")
# 最安値
ws.cell(DATA_ROW, 7).alignment = aln("right", "center")
# 画像
img_cell = ws.cell(DATA_ROW, 2)
img_cell.value     = "画像\nここに貼付"
img_cell.font      = Font(name=FONT_NAME, size=9, color="AAAAAA")
img_cell.alignment = aln("center", "center", wrap=True)

# ── Amazon側のセル個別設定 ───────────────────────────────────────────
# ライバル件数（M=13）
ws.cell(DATA_ROW, 13).alignment = aln("center", "center")
# Amazon最安値（N=14）
ws.cell(DATA_ROW, 14).alignment = aln("right", "center")
# Amazon最高値（O=15）
ws.cell(DATA_ROW, 15).alignment = aln("right", "center")
# 1688仕入値（元）（P=16）
ws.cell(DATA_ROW, 16).alignment = aln("right", "center")
# 仕入値（円）= 1688価格 × 為替レート（Q=17）自動計算
ws.cell(DATA_ROW, 17).value     = f"=IF(P{DATA_ROW}=\"\",\"\",ROUND(P{DATA_ROW}*$N$2,0))"
ws.cell(DATA_ROW, 17).alignment = aln("right", "center")
ws.cell(DATA_ROW, 17).font      = fnt(bold=False)
# Amazon販売予定価格（R=18）
ws.cell(DATA_ROW, 18).alignment = aln("right", "center")
# FBA手数料（S=19）
ws.cell(DATA_ROW, 19).alignment = aln("right", "center")
# 利益 = R - Q - S（T=20）自動計算
ws.cell(DATA_ROW, 20).value     = (
    f"=IF(OR(R{DATA_ROW}=\"\",Q{DATA_ROW}=\"\"),\"\","
    f"R{DATA_ROW}-Q{DATA_ROW}-IF(S{DATA_ROW}=\"\",0,S{DATA_ROW}))"
)
ws.cell(DATA_ROW, 20).alignment = aln("right", "center")
ws.cell(DATA_ROW, 20).font      = fnt(bold=True)
# 利益率 = T / R（U=21）自動計算
ws.cell(DATA_ROW, 21).value     = (
    f"=IF(OR(T{DATA_ROW}=\"\",R{DATA_ROW}=0),\"\","
    f"T{DATA_ROW}/R{DATA_ROW})"
)
ws.cell(DATA_ROW, 21).alignment = aln("center", "center")
ws.cell(DATA_ROW, 21).font      = fnt(bold=True)
# Amazon検索URL（V=22）
ws.cell(DATA_ROW, 22).alignment = aln("left", "center")
# Amazonメモ（W=23）
ws.cell(DATA_ROW, 23).alignment = aln("left", "center", wrap=True)


# ── 保存 ─────────────────────────────────────────────────────────────
wb.save(OUT_PATH)
print(f"✅ Amazon統合テンプレート生成完了: {OUT_PATH}")
print()
print("【列構成】")
print("  A〜L列: AucFan リサーチ（元テンプレートと同じ）")
print("  M列: ライバル件数（手入力）")
print("  N列: Amazon最安値（手入力）")
print("  O列: Amazon最高値（手入力）")
print("  P列: 1688仕入値（元・手入力）")
print("  Q列: 仕入値（円）= P × N2の為替レート（自動計算）")
print("  R列: Amazon販売予定価格（手入力）")
print("  S列: FBA手数料（手入力）")
print("  T列: 利益 = R - Q - S（自動計算）")
print("  U列: 利益率 = T ÷ R（自動計算）")
print("  V列: Amazon検索URL（手入力）")
print("  W列: Amazonメモ（手入力）")
print()
print("【為替レート】")
print(f"  N2セルに {EXCHANGE_RATE_DEFAULT}（円/元）を初期値として設定しています。")
print("  実際のレートに合わせてN2セルを書き換えてください。")
print("  仕入値（円）列が自動的に再計算されます。")
print()
print("【元のテンプレートに戻す方法】")
print("  アプリの📗 Excelボタンは リサーチ_テンプレート.xlsx を使用しています。")
print("  このファイル（リサーチ_テンプレート_Amazon.xlsx）とは別物です。")
print("  アプリから出力したい場合は:")
print("    cp リサーチ_テンプレート_Amazon.xlsx リサーチ_テンプレート.xlsx")
print("  元に戻す場合は:")
print("    python3 build_template.py")
