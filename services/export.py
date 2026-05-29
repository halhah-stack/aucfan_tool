"""
services/export.py — エクスポート関連ビジネスロジック

HTML / PDF / CSV の生成・保存・Google Drive 転送処理。
app.py のルートハンドラから切り出した純粋関数群。
Flask に依存しないため単体テスト可能。

2026-05-30 app.py から分離
"""
import os
import base64
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)

def _generate_export_html(dm, images_dir: Path) -> str:
    """
    DataManager と images_dir から HTML エクスポート文字列を生成する共通ヘルパー。
    api_export_html（ブラウザ経由）と _save_export_files（自動保存）の両方から呼ばれる。
    """
    import base64
    from collections import defaultdict

    items = dm.get_all_items()
    if not items:
        return ""

    # グループ化
    group_map = defaultdict(list)
    for item in items:
        gid = item.get("group_id") or item["item_id"]
        group_map[gid].append(item)
    groups = sorted(group_map.values(), key=lambda g: len(g), reverse=True)

    # 画像を base64 に変換
    def encode_image(local_path):
        if not local_path or not images_dir:
            return ""
        try:
            img_path = images_dir / Path(local_path).name
            if img_path.exists():
                with open(img_path, "rb") as f:
                    raw = f.read()
                ext = img_path.suffix.lower().lstrip(".")
                mime = {
                    "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png", "gif": "image/gif",
                    "webp": "image/webp",
                }.get(ext, "image/jpeg")
                return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        except Exception as e:
            logger.debug(f"画像base64変換エラー: {e}")
        return ""

    # グループデータを整形
    groups_data = []
    for group in groups:
        first = group[0]
        thumbs = [encode_image(item.get("thumbnail_local", "")) for item in group[:5]]
        thumbs = [t for t in thumbs if t]

        price    = first.get("price", 0)
        shipping = first.get("shipping", 0)
        total    = first.get("total", price + shipping)
        seller_ids = list({i.get("seller_id", "") for i in group if i.get("seller_id")})

        groups_data.append({
            "count":      len(group),
            "status":     first.get("status", "waiting"),
            "title":      (first.get("title_full") or first.get("title_short", ""))[:120],
            "price":      price,
            "shipping":   shipping,
            "total":      total,
            "seller_ids": seller_ids[:5],
            "thumbs":     thumbs,
            "url":        first.get("url", ""),
        })

    progress    = dm.get_progress()
    keyword     = progress.get("keyword", "")
    exported_at = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    return _build_export_html(groups_data, keyword, exported_at, len(items), len(groups_data))



def _save_export_files(dm, output_dir: Path):
    """
    CSV / Mac用HTML / PDF をセッションフォルダと Google Drive に自動保存する。
    セラー分析完了時・キーワードスクレイピング完了時に呼ばれる。

    Google Drive 保存先:
      ~/Library/CloudStorage/GoogleDrive-shinozakistore@gmail.com/マイドライブ/AucFanToolData/
      セッション名_Mac表示用.html  ← ブラウザで開く用
      セッション名_仕入れ候補.pdf  ← iPhone の「ファイル」アプリで開く用
    """
    import shutil

    # Google Drive 保存先フォルダ（config._GDRIVE_ROOT と同じパス）
    # メールアドレスは config.GDRIVE_EMAIL（.envで設定）から取得
    _gdrive_email = config.GDRIVE_EMAIL
    _GDRIVE_DIR = Path(os.path.expanduser(
        f"~/Library/CloudStorage/GoogleDrive-{_gdrive_email}/マイドライブ/AucFanToolData"
    )) if _gdrive_email else Path(config.OUTPUT_BASE_DIR).parent

    session_name = output_dir.name   # 例: S1_20260508_01_LEDライト
    images_dir   = Path(config.LOCAL_IMAGE_CACHE_DIR) / session_name / "images"

    # ── CSV ──
    try:
        dm.save_csv()
        logger.info(f"自動CSV保存: {output_dir / 'results.csv'}")
    except Exception as e:
        logger.error(f"CSV自動保存エラー: {e}")

    # ── Mac用HTML（セッションフォルダ + Google Drive） ──
    try:
        html_mac = _generate_export_html(dm, images_dir)
        if html_mac:
            # セッションフォルダに保存
            (output_dir / "result.html").write_text(html_mac, encoding="utf-8")
            logger.info(f"自動HTML保存(Mac用): {output_dir / 'result.html'}")
            # Google Drive にコピー
            _gdrive_copy_html(
                html_mac,
                _GDRIVE_DIR / f"{session_name}_Mac表示用.html",
                label="Mac表示用"
            )
    except Exception as e:
        logger.error(f"HTML自動保存エラー(Mac用): {e}")

    # iPhone用HTMLは廃止。iPhone向け出力はPDFに一本化。

    # ── PDF（仕入れ候補・次期候補 / 件数降順→価格降順） ──
    try:
        from pdf_exporter import generate_pdf
        pdf_bytes = generate_pdf(dm, output_dir)
        if pdf_bytes:
            # セッションフォルダに保存
            pdf_path = output_dir / "result.pdf"
            pdf_path.write_bytes(pdf_bytes)
            logger.info(f"自動PDF保存: {pdf_path}")
            # Google Drive にPDFを保存
            # scraper Mac（十王）: GDrive API で直接アップロード
            # reader  Mac（守谷）: ミラーリング経由でファイル書き込み
            if config.SITE_ROLE == "scraper" and config.GDRIVE_UPLOAD_ENABLED:
                try:
                    import gdrive_uploader
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                        tf.write(pdf_bytes)
                        tmp_path = Path(tf.name)
                    folder_id = gdrive_uploader.get_or_create_folder_path(
                        ["AucFanToolData", "リサーチ結果", session_name]
                    )
                    if folder_id:
                        gdrive_uploader.upload_file(
                            tmp_path, folder_id, f"{session_name}_仕入れ候補.pdf"
                        )
                        logger.info(f"Google Drive PDF保存(API): {session_name}_仕入れ候補.pdf")
                    tmp_path.unlink(missing_ok=True)
                except Exception as e2:
                    logger.warning(f"Google Drive PDF保存(API)スキップ: {e2}")
            else:
                gdrive_pdf = _GDRIVE_DIR / f"{session_name}_仕入れ候補.pdf"
                try:
                    gdrive_pdf.parent.mkdir(parents=True, exist_ok=True)
                    gdrive_pdf.write_bytes(pdf_bytes)
                    logger.info(f"Google Drive PDF保存: {gdrive_pdf}")
                except Exception as e2:
                    logger.warning(f"Google Drive PDF保存スキップ: {e2}")
        else:
            logger.info("PDF出力スキップ（候補グループなし）")
    except Exception as e:
        logger.error(f"PDF自動保存エラー: {e}")




def _gdrive_copy_html(html_content: str, dest_path: Path, label: str = ""):
    """
    HTML 文字列を Google Drive の指定パスに書き込む。
    Google Drive フォルダが存在しない場合は自動作成する。
    エラーが発生しても例外を握り潰してメインフローを止めない。
    """
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(html_content, encoding="utf-8")
        logger.info(f"Google Drive 保存({label}): {dest_path}")
    except Exception as e:
        logger.warning(f"Google Drive 保存スキップ({label}): {e}")



def _build_export_html(groups_data, keyword, exported_at, total_items, total_groups):
    """iPhone/iPad 向けスタンドアロン HTML を生成する"""
    import json
    groups_json = json.dumps(groups_data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AucFan リサーチ結果 - {keyword}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --primary: #2563eb; --primary-dark: #1d4ed8;
      --success: #16a34a; --warning: #d97706;
      --danger: #dc2626; --review: #7c3aed;
      --gray-50: #f9fafb; --gray-100: #f3f4f6;
      --gray-200: #e5e7eb; --gray-300: #d1d5db;
      --gray-600: #4b5563; --gray-700: #374151;
      --gray-900: #111827;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif;
      font-size: 14px; background: var(--gray-50);
      color: var(--gray-900); line-height: 1.5;
    }}
    /* ─ ヘッダー ─ */
    .header {{
      background: var(--primary); color: #fff;
      position: sticky; top: 0; z-index: 100;
      padding: 10px 16px; box-shadow: 0 2px 6px rgba(0,0,0,.2);
    }}
    .header h1 {{ font-size: 16px; font-weight: 700; }}
    .header-meta {{ font-size: 11px; opacity: .8; margin-top: 2px; }}
    /* ─ フィルタータブ ─ */
    .filter-bar {{
      background: #fff; border-bottom: 1px solid var(--gray-200);
      padding: 8px 12px; overflow-x: auto; white-space: nowrap;
    }}
    .filter-bar button {{
      display: inline-block; padding: 5px 14px; margin-right: 6px;
      border: 1px solid var(--gray-300); border-radius: 20px;
      background: #fff; font-size: 13px; cursor: pointer; white-space: nowrap;
    }}
    .filter-bar button.active {{
      background: var(--primary); color: #fff; border-color: var(--primary);
    }}
    /* ─ 統計バー ─ */
    .stats {{
      background: #fff; padding: 8px 16px;
      display: flex; gap: 10px; flex-wrap: wrap;
      border-bottom: 1px solid var(--gray-200); font-size: 12px;
    }}
    .stat {{ text-align: center; }}
    .stat-num {{ font-size: 18px; font-weight: 700; }}
    .stat-label {{ color: var(--gray-600); }}
    /* ─ 検索バー ─ */
    .search-bar {{
      padding: 8px 12px; background: var(--gray-50);
      border-bottom: 1px solid var(--gray-200);
    }}
    .search-bar input {{
      width: 100%; padding: 8px 12px;
      border: 1px solid var(--gray-300); border-radius: 20px;
      font-size: 14px; outline: none;
    }}
    /* ─ グリッド ─ */
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 12px; padding: 12px;
    }}
    @media (max-width: 480px) {{ .grid {{ grid-template-columns: 1fr; }} }}
    /* ─ カード ─ */
    .card {{
      background: #fff; border-radius: 10px;
      box-shadow: 0 1px 3px rgba(0,0,0,.1);
      overflow: hidden; border: 2px solid transparent;
    }}
    .card.candidate {{ border-color: var(--primary); }}
    .card.ok         {{ border-color: var(--success); }}
    .card.review     {{ border-color: var(--review); }}
    .card.ng         {{ opacity: .5; }}
    /* ステータスバー */
    .card-status {{
      padding: 5px 12px; font-size: 11px; font-weight: 700;
      color: #fff; display: flex; justify-content: space-between;
    }}
    .card-status.candidate {{ background: var(--primary); }}
    .card-status.waiting   {{ background: var(--gray-600); }}
    .card-status.review    {{ background: var(--review); }}
    .card-status.ok        {{ background: var(--success); }}
    .card-status.ng        {{ background: var(--danger); }}
    /* サムネール */
    .card-images {{
      display: flex; gap: 4px; padding: 8px;
      overflow-x: auto; background: var(--gray-50); min-height: 80px;
    }}
    .card-images img {{
      width: 72px; height: 72px; object-fit: cover;
      border-radius: 6px; flex-shrink: 0;
    }}
    .no-image {{
      width: 72px; height: 72px; border-radius: 6px;
      background: var(--gray-200); display: flex;
      align-items: center; justify-content: center;
      font-size: 24px; flex-shrink: 0;
    }}
    /* カード本文 */
    .card-body {{ padding: 10px 12px; }}
    .card-title {{
      font-size: 13px; font-weight: 600; line-height: 1.4;
      margin-bottom: 8px;
      display: -webkit-box; -webkit-line-clamp: 2;
      -webkit-box-orient: vertical; overflow: hidden;
    }}
    .card-price-row {{
      display: flex; gap: 12px; margin-bottom: 6px; font-size: 13px;
    }}
    .card-price {{ font-size: 18px; font-weight: 700; color: var(--danger); }}
    .card-price-label {{ font-size: 10px; color: var(--gray-600); }}
    .card-price-sub {{ font-weight: 600; }}
    .card-sellers {{
      font-size: 11px; color: var(--gray-600); margin-bottom: 8px;
    }}
    .seller-badge {{
      display: inline-block; background: var(--gray-100);
      border-radius: 3px; padding: 1px 5px; margin-right: 2px;
      font-family: monospace;
    }}
    .group-badge {{
      display: inline-block; background: #dbeafe;
      color: var(--primary); border-radius: 4px;
      padding: 2px 8px; font-weight: 700; font-size: 12px;
    }}
    /* アクション */
    .card-actions {{
      display: flex; gap: 6px; flex-wrap: wrap;
      padding: 8px 12px; border-top: 1px solid var(--gray-100);
      background: var(--gray-50);
    }}
    .btn {{
      display: inline-flex; align-items: center;
      padding: 7px 14px; border: none; border-radius: 6px;
      font-size: 13px; font-weight: 600; cursor: pointer;
      text-decoration: none; color: inherit;
    }}
    .btn-gray  {{ background: var(--gray-200); color: var(--gray-700); }}
    /* カウント表示 */
    .count-info {{
      text-align: center; padding: 12px;
      color: var(--gray-600); font-size: 13px;
    }}
    /* empty */
    .empty {{
      text-align: center; padding: 60px 20px; color: var(--gray-600);
    }}
    .empty-icon {{ font-size: 48px; margin-bottom: 12px; }}
  </style>
</head>
<body>

<div class="header">
  <h1>🔍 AucFan リサーチ結果</h1>
  <div class="header-meta">
    キーワード: {keyword} ／ {total_items}件 / {total_groups}グループ ／ 書き出し: {exported_at}
  </div>
</div>

<div class="filter-bar" id="filterBar">
  <button class="active" onclick="setFilter('')">すべて</button>
  <button onclick="setFilter('candidate')">🔵 仕入れ候補</button>
  <button onclick="setFilter('ok')">✅ OK</button>
  <button onclick="setFilter('waiting')">⏳ 確認待ち</button>
  <button onclick="setFilter('review')">⚠️ 要確認</button>
  <button onclick="setFilter('ng')">❌ NG</button>
</div>

<div class="search-bar">
  <input type="search" id="searchInput" placeholder="タイトルで絞り込み..."
         oninput="renderCards()" autocomplete="off" autocorrect="off">
</div>

<div id="countInfo" class="count-info"></div>
<div class="grid" id="grid"></div>

<script>
const GROUPS = {groups_json};

let currentFilter = '';

function setFilter(status) {{
  currentFilter = status;
  document.querySelectorAll('#filterBar button').forEach(btn => btn.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('searchInput').value = '';
  renderCards();
}}

function esc(str) {{
  if (!str) return '';
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

const STATUS_LABEL = {{
  candidate: '仕入れ候補', waiting: '確認待ち',
  review: '要確認', ok: '✅ OK', ng: '❌ NG'
}};

function renderCards() {{
  const grid = document.getElementById('grid');
  const kw   = document.getElementById('searchInput').value.trim().toLowerCase();

  const filtered = GROUPS.filter(g => {{
    if (currentFilter && g.status !== currentFilter) return false;
    if (kw && !g.title.toLowerCase().includes(kw)) return false;
    return true;
  }});

  document.getElementById('countInfo').textContent =
    `表示中: ${{filtered.length}} グループ`;

  if (filtered.length === 0) {{
    grid.innerHTML = '<div class="empty"><div class="empty-icon">📦</div><p>該当する商品がありません</p></div>';
    return;
  }}

  grid.innerHTML = filtered.map(g => {{
    const statusLabel = STATUS_LABEL[g.status] || g.status;
    const countLabel  = g.count > 1
      ? `同一商品 <span class="group-badge">${{g.count}}件</span>` : '単品';

    const thumbsHtml = g.thumbs.length > 0
      ? g.thumbs.map(src => `<img src="${{src}}" loading="lazy" alt="">`).join('')
      : '<div class="no-image">📦</div>';

    const shipping = g.shipping === 0 ? '無料' : '¥' + g.shipping.toLocaleString();
    const sellers  = (g.seller_ids || []).map(s => `<span class="seller-badge">${{esc(s)}}</span>`).join('');

    const searchQ  = encodeURIComponent((g.title || '').substring(0, 50));
    const aliUrl   = `https://aliprice.com/search?q=${{searchQ}}`;
    const amaUrl   = `https://www.amazon.co.jp/s?k=${{searchQ}}`;

    return `<div class="card ${{g.status}}">
      <div class="card-status ${{g.status}}">
        <span>${{esc(statusLabel)}}</span>
        <span>${{countLabel}}</span>
      </div>
      <div class="card-images">${{thumbsHtml}}</div>
      <div class="card-body">
        <div class="card-title">${{esc(g.title || '（タイトルなし）')}}</div>
        <div class="card-price-row">
          <div>
            <div class="card-price-label">合計</div>
            <div class="card-price">¥${{(g.total||0).toLocaleString()}}</div>
          </div>
          <div>
            <div class="card-price-label">落札価格</div>
            <div class="card-price-sub">¥${{(g.price||0).toLocaleString()}}</div>
          </div>
          <div>
            <div class="card-price-label">送料</div>
            <div class="card-price-sub">${{shipping}}</div>
          </div>
        </div>
        <div class="card-sellers">出品者: ${{sellers || '—'}}</div>
      </div>
      <div class="card-actions">
        <a class="btn btn-gray" href="${{aliUrl}}" target="_blank" rel="noopener">🛒 AliPrice</a>
        <a class="btn btn-gray" href="${{amaUrl}}" target="_blank" rel="noopener">📦 Amazon</a>
        ${{g.url ? `<a class="btn btn-gray" href="${{esc(g.url)}}" target="_blank" rel="noopener">🔗 元ページ</a>` : ''}}
      </div>
    </div>`;
  }}).join('');
}}

renderCards();
</script>
</body>
</html>"""


