"""
app.py — AucFan リサーチツール メインエントリーポイント

【役割】
  - Flask Webアプリ起動（ポート 5001、0.0.0.0 バインドで iPhone/iPad からも接続可能）
  - AucFanScraper / SellerAnalyzer をバックグラウンドスレッドで実行
  - スクレイピング進捗を SSE（Server-Sent Events）でリアルタイム配信
  - STEP 1（キーワードリサーチ）/ STEP 2（セラーリサーチ）/ STEP 3（マスターリサーチ）
    の3ステップ分の API エンドポイントを提供

【グローバル状態】
  _data_manager      : STEP 1 用 DataManager（スクレイパースレッドと共有）
  _scraper_thread    : STEP 1 スクレイピングスレッド
  _stop_event        : 停止シグナル（set() で全スレッドに停止を通知）
  _seller_state      : STEP 2（セラーリサーチ）の実行状態
  _master_state      : STEP 3（マスターセラーリサーチ）の実行状態
  _sellers_master    : SellersMaster シングルトン（data/sellers_master.json を管理）

【werkzeug ログ抑制】
  werkzeug のアクセスログ（ポーリング系 GET /api/... 200 の大量ログ）は
  Warning レベルに抑制済み。スクレイピング完了後は logger.info で
  「待機中」メッセージをターミナルに表示する。
"""
import json
import logging
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import io
import shutil
import pandas as pd
from flask import (
    Flask, Response, jsonify, render_template, request,
    send_from_directory, abort
)

import config
from data_manager import DataManager, make_output_dir, make_session_id
from image_processor import ImageProcessor
from gemini_client import GeminiClient, get_rate_limit_status, reset_rate_limit_flag
from scraper import AucFanScraper
from seller_analyzer import SellerAnalyzer
from sellers_master import SellersMaster

# ─────────────────────────────────────────────
# ロギング設定
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# werkzeug のアクセスログを抑制（ポーリング系の大量ログを非表示にする）
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# ─────────────────────────────────────────────
# Flask アプリ
# ─────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.urandom(24)

# ─── STEP 1: キーワードリサーチ グローバル状態 ───
# スクレイパースレッドと Flask ルートハンドラが同一オブジェクトを共有する。
# 操作は _lock でスレッドセーフに保護する。
_scraper_thread: threading.Thread = None
_stop_event = threading.Event()          # set() でスクレイパーに停止を通知
_data_manager: DataManager = None        # 現在アクティブな DataManager
_image_processor: ImageProcessor = None  # 画像ダウンロード・pHash 計算
_gemini_client: GeminiClient = None      # Gemini API クライアント
_session_output_dir: Path = None         # 現セッションの出力ディレクトリ
_lock = threading.Lock()

# ─── STEP 2: セラーリサーチ グローバル状態 ───
# SellerAnalyzer スレッドと Flask ルートハンドラが共有する辞書。
# 操作は _seller_lock でスレッドセーフに保護する。
_seller_state = {
    "sellers": [],        # [{"seller_id": str, "seller_url": str, "status": "pending"|"running"|"done"|"error"}]
    "current_index": -1,  # 現在処理中のセラーインデックス（-1 = 未開始）
    "running": False,     # SellerAnalyzer スレッドが実行中かどうか
    "phase": "idle",      # "idle"|"scraping_list"|"grouping"|"vision_check"|"done"|"stopped"|"error"
    "stop_event": None,   # threading.Event（実行中のみ有効、停止リクエスト用）
    "thread": None,       # SellerAnalyzer スレッド
    "dm": None,           # 実行中の DataManager（/api/seller/status でのポーリング用）
    "session_id": None,   # 完了セッション ID（履歴表示用）
    "output_dir": None,   # 完了セッション出力ディレクトリ（Path）
}
_seller_lock = threading.Lock()

# ─── STEP 3: マスターセラーリサーチ グローバル状態 ───
# _seller_state と同じ構造。SellersMaster からセラーを自動取得して
# SellerAnalyzer を順次実行する。
_master_state = {
    "running": False,
    "phase": "idle",       # "idle"|"scraping_list"|"grouping"|"vision_check"|"done"|"stopped"|"error"
    "stop_event": None,    # threading.Event（実行中のみ有効）
    "thread": None,        # SellerAnalyzer スレッド
    "dm": None,            # 実行中の DataManager
    "session_id": None,
    "output_dir": None,
    "total": 0,
    "done": 0,
    "current_seller": "",
}
_master_lock = threading.Lock()
_sellers_master = SellersMaster()   # シングルトン


def get_dm() -> DataManager:
    """
    グローバルな DataManager インスタンスを返すヘルパー。

    スクレイピングスレッドと Flask ルートハンドラが同一の DataManager を
    共有するためのシングルトンアクセスポイント。
    読み取り専用アクセスのためロック不要で呼び出せる。
    スクレイピング未開始・データ未ロード時は None を返す。
    """
    global _data_manager
    return _data_manager


# ─────────────────────────────────────────────
# ルート
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/images/<path:filename>")
def serve_image(filename):
    """保存済み画像を配信"""
    if _session_output_dir is None:
        abort(404)
    images_dir = _session_output_dir / "images"
    return send_from_directory(str(images_dir), filename)


# ─────────────────────────────────────────────
# スクレイピング制御
# ─────────────────────────────────────────────

@app.route("/api/start", methods=["POST"])
def api_start():
    """スクレイピング開始"""
    global _scraper_thread, _stop_event, _data_manager, _image_processor
    global _gemini_client, _session_output_dir

    with _lock:
        if _scraper_thread and _scraper_thread.is_alive():
            return jsonify({"success": False, "message": "スクレイピングは既に実行中です"}), 400

        data = request.get_json(silent=True) or {}
        keyword   = data.get("keyword", "unknown")
        resume    = data.get("resume", False)
        start_url = data.get("start_url", "").strip()  # iPhoneから貼り付けたURL（任意）

        # セッション初期化 (S1_YYYYMMDD_NN_keyword)
        out_dir, session_id = make_output_dir(keyword, step=1)
        _session_output_dir = out_dir
        _data_manager = DataManager(session_id, out_dir)
        _image_processor = ImageProcessor(out_dir / "images")
        _gemini_client = GeminiClient()

        # 再開の場合は前回データをロード
        if resume:
            _data_manager.load_previous_session()

        _stop_event.clear()

        def run_scraper():
            scraper = AucFanScraper(
                data_manager=_data_manager,
                image_processor=_image_processor,
                gemini_client=_gemini_client,
                stop_event=_stop_event,
            )
            scraper.run(resume=resume, start_url=start_url or None)

        _scraper_thread = threading.Thread(target=run_scraper, daemon=True, name="scraper")
        _scraper_thread.start()

        logger.info(f"スクレイピング開始: keyword={keyword}, session={session_id}, start_url={start_url or '（現在タブ）'}")
        return jsonify({
            "success": True,
            "session_id": session_id,
            "output_dir": str(out_dir),
            "resume": resume,
            "start_url": start_url or None,
        })


@app.route("/api/stop", methods=["POST"])
def api_stop():
    """スクレイピングを停止"""
    _stop_event.set()
    logger.info("停止リクエストを受け取りました")
    return jsonify({"success": True, "message": "停止中..."})


@app.route("/api/resume", methods=["POST"])
def api_resume():
    """前回セッションを選択して再開準備"""
    sessions = _list_sessions()
    return jsonify({"sessions": sessions})


# ─────────────────────────────────────────────
# SSE（リアルタイム進捗）
# ─────────────────────────────────────────────

@app.route("/api/stream")
def api_stream():
    """Server-Sent Events で進捗をリアルタイム配信"""
    def generate():
        # SSEペイロード構造（クライアントの updateProgressUI が期待するフィールド）:
        #   progress          : DataManager.get_progress() の戻り値（dict）
        #     .status         : 'idle'|'scraping_list'|'scraping_detail'|'grouping'|
        #                       'vision_check'|'done'|'stopped'|'error'
        #     .keyword        : スクレイピング対象キーワード
        #     .pages_done     : 取得済み一覧ページ数
        #     .total_pages    : 推定総ページ数
        #     .total_items    : 取得済み商品数（累計）
        #     .detail_pages_done  : 詳細取得済み件数
        #     .detail_pages_total : 詳細取得対象の総件数
        #     .candidates_found   : 仕入れ候補として検出された件数
        #     .processed_items    : 処理（判定）済みアイテム数
        #   stats             : DataManager.get_stats() の戻り値（dict）
        #     .total          : 全アイテム数
        #     .by_status      : {candidate, next_candidate, ok, ng, review, waiting} 各件数
        #   is_running        : スクレイパースレッドが生存中かどうか (bool)
        #   gemini_enabled    : Gemini API が有効かどうか (bool)
        #   is_seller_analysis: セラー分析モード中かどうか（keyword == 'seller_analysis'）(bool)
        last_total = -1
        while True:
            try:
                dm = get_dm()
                if dm:
                    progress = dm.get_progress()
                    stats = dm.get_stats()
                    is_running = _scraper_thread is not None and _scraper_thread.is_alive()

                    payload = {
                        "progress": progress,
                        "stats": stats,
                        "is_running": is_running,
                        "gemini_enabled": _gemini_client.available if _gemini_client else False,
                        "is_seller_analysis": progress.get("keyword", "") == "seller_analysis",
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'progress': {'status': 'idle'}, 'is_running': False})}\n\n"
            except GeneratorExit:
                break
            except Exception as e:
                logger.debug(f"SSEエラー: {e}")
            time.sleep(1.5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ─────────────────────────────────────────────
# データ取得 API
# ─────────────────────────────────────────────

@app.route("/api/progress")
def api_progress():
    """現在の進捗を返す"""
    dm = get_dm()
    if not dm:
        return jsonify({"status": "idle", "total_items": 0})
    return jsonify({
        "progress": dm.get_progress(),
        "stats": dm.get_stats(),
        "is_running": _scraper_thread is not None and _scraper_thread.is_alive(),
    })


@app.route("/api/items")
def api_items():
    """商品一覧をグループ形式で返す"""
    dm = get_dm()
    if not dm:
        return jsonify({"groups": []})

    # フィルターパラメータ
    keyword = request.args.get("keyword", "")
    status = request.args.get("status", "")
    min_price = int(request.args.get("min_price", 0))
    max_price = int(request.args.get("max_price", 99999))
    min_group = int(request.args.get("min_group", 0))
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 30))

    filtered = dm.get_items_filtered(
        keyword=keyword,
        status=status,
        min_price=min_price,
        max_price=max_price,
        min_group=min_group,
    )

    # グループ化
    group_map = {}
    for item in filtered:
        gid = item.get("group_id") or item["item_id"]
        group_map.setdefault(gid, []).append(item)

    # グループサイズで降順ソート
    groups = sorted(group_map.values(), key=lambda g: len(g), reverse=True)

    # ページネーション
    total_groups = len(groups)
    start = (page - 1) * per_page
    end = start + per_page
    page_groups = groups[start:end]

    # シリアライズ用に整形
    result_groups = []
    for group in page_groups:
        result_groups.append({
            "group_id": group[0].get("group_id") or group[0]["item_id"],
            "count": len(group),
            "items": group,
            "status": group[0].get("status", ""),
            "title": (group[0].get("title_full") or group[0].get("title_short", ""))[:100],
            "min_price": min((int(i.get("price") or 0) for i in group if int(i.get("price") or 0) > 0), default=0),
            "max_price": max((int(i.get("price") or 0) for i in group if int(i.get("price") or 0) > 0), default=0),
            "seller_ids": list(set(i.get("seller_id", "") for i in group if i.get("seller_id"))),
        })

    progress = dm.get_progress()
    return jsonify({
        "groups": result_groups,
        "total_groups": total_groups,
        "page": page,
        "per_page": per_page,
        "total_pages": (total_groups + per_page - 1) // per_page,
        "is_seller_analysis": progress.get("keyword", "") == "seller_analysis",
        "seller_detail_min_group": config.SELLER_DETAIL_MIN_GROUP,
    })


@app.route("/api/item/<item_id>")
def api_item_detail(item_id):
    """個別商品の詳細"""
    dm = get_dm()
    if not dm:
        abort(404)
    item = dm.get_item(item_id)
    if not item:
        abort(404)
    return jsonify(item)


# ─────────────────────────────────────────────
# ステータス更新 API
# ─────────────────────────────────────────────

@app.route("/api/item/<item_id>/status", methods=["POST"])
def api_update_status(item_id):
    """商品ステータスを更新（OK / NG / etc.）"""
    dm = get_dm()
    if not dm:
        return jsonify({"success": False}), 400

    data = request.get_json(silent=True) or {}
    new_status = data.get("status")

    valid_statuses = [config.STATUS_OK, config.STATUS_NG, config.STATUS_CANDIDATE,
                      config.STATUS_WAITING, config.STATUS_REVIEW]
    if new_status not in valid_statuses:
        return jsonify({"success": False, "message": f"無効なステータス: {new_status}"}), 400

    dm.update_status(item_id, new_status)

    # グループ全体に反映する場合
    apply_group = data.get("apply_group", False)
    if apply_group:
        item = dm.get_item(item_id)
        if item and item.get("group_id"):
            all_items = dm.get_all_items()
            for i in all_items:
                if i.get("group_id") == item["group_id"]:
                    dm.update_status(i["item_id"], new_status)

    dm.save_csv()
    return jsonify({"success": True, "item_id": item_id, "status": new_status})


@app.route("/api/group/<group_id>/status", methods=["POST"])
def api_update_group_status(group_id):
    """グループ全体のステータスを更新"""
    dm = get_dm()
    if not dm:
        return jsonify({"success": False}), 400

    data = request.get_json(silent=True) or {}
    new_status = data.get("status")

    all_items = dm.get_all_items()
    updated = 0
    for item in all_items:
        if item.get("group_id") == group_id or item["item_id"] == group_id:
            dm.update_status(item["item_id"], new_status)
            updated += 1

    dm.save_csv()
    return jsonify({"success": True, "updated": updated})


# ─────────────────────────────────────────────
# CSV エクスポート
# ─────────────────────────────────────────────

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


def _generate_offline_html(dm, images_dir: Path, only_active: bool = False) -> str:
    """
    iPhone/iPad向けオフライン用HTML。画像をすべてbase64埋め込み、外部リソース参照なし。
    シンプルな縦1カラムレイアウトでモバイル画面に最適化。

    Args:
        dm          : DataManager インスタンス
        images_dir  : ローカル画像フォルダ
        only_active : True のとき candidate/next_candidate/ok/review のみ出力し
                      waiting/ng を除外する（ファイルサイズ削減）
    """
    import base64
    from collections import defaultdict

    items = dm.get_all_items()

    # only_active=True: 確認待ちと NG を除外して軽量化
    if only_active:
        _active = {"candidate", "next_candidate", "ok", "review"}
        items = [i for i in items if i.get("status", "waiting") in _active]

    if not items:
        return ""

    # グループ化
    group_map = defaultdict(list)
    for item in items:
        gid = item.get("group_id") or item["item_id"]
        group_map[gid].append(item)
    groups = sorted(group_map.values(), key=lambda g: len(g), reverse=True)

    # 1x1 グレープレースホルダー GIF (base64)
    PLACEHOLDER = (
        "data:image/gif;base64,R0lGODlhAQABAIAAAMLCwgAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw=="
    )

    def encode_image(local_path):
        """
        画像をbase64エンコードして返す。
        PIL でリサイズ（120×120）＋JPEG圧縮（quality=35）を行い
        ファイルサイズを大幅に削減する（iPhone Safari の読み込み制限対策）。
        """
        if not local_path or not images_dir:
            return PLACEHOLDER
        try:
            img_path = images_dir / Path(local_path).name
            if img_path.exists():
                from PIL import Image as PILImage
                img = PILImage.open(img_path)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                img.thumbnail((120, 120), PILImage.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=35, optimize=True)
                raw = buf.getvalue()
                return f"data:image/jpeg;base64,{base64.b64encode(raw).decode()}"
        except Exception as e:
            logger.debug(f"オフラインHTML画像変換エラー: {e}")
        return PLACEHOLDER

    # カードHTMLを組み立て
    STATUS_LABEL = {
        "candidate": "🔵 仕入れ候補",
        "waiting":   "⏳ 確認待ち",
        "review":    "⚠️ 要確認",
        "ok":        "✅ OK",
        "ng":        "❌ NG",
    }
    STATUS_COLOR = {
        "candidate": "#2563eb",
        "waiting":   "#6b7280",
        "review":    "#7c3aed",
        "ok":        "#16a34a",
        "ng":        "#dc2626",
    }
    STATUS_BG = {
        "candidate": "#eff6ff",
        "waiting":   "#f9fafb",
        "review":    "#f5f3ff",
        "ok":        "#f0fdf4",
        "ng":        "#fef2f2",
    }

    cards_html = ""
    for group in groups:
        first = group[0]
        status   = first.get("status", "waiting")
        title    = (first.get("title_full") or first.get("title_short", ""))[:100]
        price    = first.get("price", 0)
        shipping = first.get("shipping", 0)
        total    = first.get("total", price + shipping)
        count    = len(group)
        seller_ids = list({i.get("seller_id", "") for i in group if i.get("seller_id")})[:3]

        # サムネイル（最大3枚）
        thumbs = []
        for item in group[:3]:
            src = encode_image(item.get("thumbnail_local", ""))
            thumbs.append(src)

        thumb_imgs = "".join(
            f'<img src="{src}" alt="" style="width:80px;height:80px;object-fit:cover;border-radius:6px;flex-shrink:0;">'
            for src in thumbs
        )
        if not thumb_imgs:
            thumb_imgs = '<div style="width:80px;height:80px;background:#e5e7eb;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:28px;flex-shrink:0;">📦</div>'

        label_color = STATUS_COLOR.get(status, "#6b7280")
        card_bg     = STATUS_BG.get(status, "#f9fafb")
        label_text  = STATUS_LABEL.get(status, status)
        shipping_str = "無料" if shipping == 0 else f"¥{shipping:,}"
        sellers_str  = "　".join(seller_ids) if seller_ids else "—"
        count_str    = f'<span style="background:#dbeafe;color:#2563eb;border-radius:4px;padding:2px 7px;font-weight:700;font-size:12px;">{count}件</span>' if count > 1 else ""
        ng_opacity   = "opacity:0.5;" if status == "ng" else ""

        # 元URLがあればリンクを追加
        import html as _html
        url       = first.get("url", "")
        url_link  = f'<a href="{_html.escape(url)}" style="display:inline-block;padding:6px 14px;background:#e5e7eb;border-radius:6px;font-size:13px;color:#374151;text-decoration:none;font-weight:600;">🔗 元ページ</a>' if url else ""

        cards_html += f"""
<div style="background:#fff;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:12px;overflow:hidden;border-left:4px solid {label_color};{ng_opacity}background:{card_bg};">
  <div style="background:{label_color};color:#fff;padding:5px 12px;font-size:12px;font-weight:700;display:flex;justify-content:space-between;align-items:center;">
    <span>{_html.escape(label_text)}</span>
    <span>{count_str}</span>
  </div>
  <div style="display:flex;gap:6px;padding:8px;overflow-x:auto;background:#f9fafb;">
    {thumb_imgs}
  </div>
  <div style="padding:10px 12px;">
    <div style="font-size:13px;font-weight:600;line-height:1.4;margin-bottom:8px;color:#111827;">{_html.escape(title or '（タイトルなし）')}</div>
    <div style="display:flex;gap:16px;margin-bottom:6px;flex-wrap:wrap;">
      <div><div style="font-size:10px;color:#6b7280;">合計</div><div style="font-size:18px;font-weight:700;color:#dc2626;">¥{total:,}</div></div>
      <div><div style="font-size:10px;color:#6b7280;">落札価格</div><div style="font-size:14px;font-weight:600;">¥{price:,}</div></div>
      <div><div style="font-size:10px;color:#6b7280;">送料</div><div style="font-size:14px;font-weight:600;">{shipping_str}</div></div>
    </div>
    <div style="font-size:11px;color:#6b7280;margin-bottom:8px;">出品者: {_html.escape(sellers_str)}</div>
    {url_link}
  </div>
</div>"""

    progress    = dm.get_progress()
    keyword     = progress.get("keyword", "")
    total_items = len(items)
    total_groups = len(groups)
    exported_at = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <title>AucFan {keyword} - オフライン閲覧用</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Hiragino Sans', 'Noto Sans JP', sans-serif;
      font-size: 14px; background: #f3f4f6; color: #111827;
      line-height: 1.5; -webkit-text-size-adjust: 100%;
    }}
    .header {{
      background: #2563eb; color: #fff;
      position: sticky; top: 0; z-index: 100;
      padding: 10px 14px; box-shadow: 0 2px 6px rgba(0,0,0,.2);
    }}
    .header h1 {{ font-size: 15px; font-weight: 700; }}
    .header-meta {{ font-size: 11px; opacity: .85; margin-top: 2px; }}
    .filter-bar {{
      background: #fff; border-bottom: 1px solid #e5e7eb;
      padding: 8px 12px; overflow-x: auto; white-space: nowrap;
      -webkit-overflow-scrolling: touch;
    }}
    .filter-bar button {{
      display: inline-block; padding: 5px 13px; margin-right: 6px;
      border: 1px solid #d1d5db; border-radius: 20px;
      background: #fff; font-size: 13px; cursor: pointer;
      font-family: inherit;
    }}
    .filter-bar button.active {{ background: #2563eb; color: #fff; border-color: #2563eb; }}
    .search-wrap {{ padding: 8px 12px; background: #f3f4f6; border-bottom: 1px solid #e5e7eb; }}
    .search-wrap input {{
      width: 100%; padding: 8px 14px; border: 1px solid #d1d5db;
      border-radius: 20px; font-size: 14px; outline: none;
      font-family: inherit; background: #fff;
    }}
    .count-bar {{ padding: 6px 14px; font-size: 12px; color: #6b7280; background: #f9fafb; }}
    .cards {{ padding: 12px; max-width: 680px; margin: 0 auto; }}
    .empty {{ text-align:center; padding:60px 20px; color:#6b7280; font-size:14px; }}
  </style>
</head>
<body>

<div class="header">
  <h1>🔍 AucFan リサーチ結果</h1>
  <div class="header-meta">
    {_html.escape(keyword)} ／ {total_items}件 / {total_groups}グループ ／ {exported_at}
  </div>
</div>

<div class="filter-bar" id="filterBar">
  <button class="active" data-filter="">すべて</button>
  <button data-filter="candidate">🔵 仕入れ候補</button>
  <button data-filter="ok">✅ OK</button>
  <button data-filter="waiting">⏳ 確認待ち</button>
  <button data-filter="review">⚠️ 要確認</button>
  <button data-filter="ng">❌ NG</button>
</div>

<div class="search-wrap">
  <input type="search" id="searchInput" placeholder="タイトルで絞り込み..."
         autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
</div>

<div class="count-bar" id="countBar"></div>
<div class="cards" id="cards">{cards_html}</div>

<script>
(function() {{
  var allCards = Array.from(document.querySelectorAll('#cards > div'));
  var currentFilter = '';

  // フィルターボタン
  document.getElementById('filterBar').addEventListener('click', function(e) {{
    var btn = e.target.closest('button');
    if (!btn) return;
    document.querySelectorAll('#filterBar button').forEach(function(b) {{ b.classList.remove('active'); }});
    btn.classList.add('active');
    currentFilter = btn.dataset.filter;
    document.getElementById('searchInput').value = '';
    applyFilter();
  }});

  // 検索
  document.getElementById('searchInput').addEventListener('input', applyFilter);

  function applyFilter() {{
    var kw = document.getElementById('searchInput').value.trim().toLowerCase();
    var shown = 0;
    allCards.forEach(function(card) {{
      var statusDiv = card.querySelector('[data-status]');
      var status = card.dataset ? card.dataset.status : '';
      // data-status 属性が取れない場合はボーダー色から判定しない → タイトルテキストで検索
      var titleEl = card.querySelectorAll('div')[5]; // 6番目のdivがtitle
      var titleText = titleEl ? titleEl.textContent.toLowerCase() : '';

      var matchFilter = !currentFilter || card.dataset.status === currentFilter;
      var matchSearch = !kw || titleText.includes(kw);

      if (matchFilter && matchSearch) {{
        card.style.display = '';
        shown++;
      }} else {{
        card.style.display = 'none';
      }}
    }});
    document.getElementById('countBar').textContent = '表示中: ' + shown + ' グループ';
  }}

  // 各カードに data-status を付与
  // (status はCSSボーダー色から取れないため、カード順序から推定できないので
  //  カードのヘッダーテキストからstatus文字列を逆引き)
  var labelToStatus = {{
    '仕入れ候補': 'candidate', '確認待ち': 'waiting',
    '要確認': 'review', 'OK': 'ok', 'NG': 'ng'
  }};
  allCards.forEach(function(card) {{
    var hdr = card.querySelector('div > span');
    if (hdr) {{
      var txt = hdr.textContent.trim().replace(/[🔵⏳⚠️✅❌]/gu, '').trim();
      for (var lbl in labelToStatus) {{
        if (txt.indexOf(lbl) >= 0) {{
          card.dataset.status = labelToStatus[lbl];
          break;
        }}
      }}
    }}
  }});

  applyFilter();
}})();
</script>
</body>
</html>"""


def _save_export_files(dm, output_dir: Path):
    """
    CSV / Mac用HTML / iPhone用HTML をセッションフォルダと Google Drive に自動保存する。
    セラー分析完了時・キーワードスクレイピング完了時に呼ばれる。

    Google Drive 保存先:
      ~/Library/CloudStorage/GoogleDrive-shinozakistore@gmail.com/マイドライブ/AucFanToolData/
      セッション名_Mac表示用.html   ← ブラウザで開く用
      セッション名_iPhone表示用.html ← iPhone の「ファイル」アプリで開く用（base64画像埋め込み）
    """
    import shutil

    # Google Drive 保存先フォルダ
    _GDRIVE_DIR = Path(
        "/Users/shino/Library/CloudStorage/"
        "GoogleDrive-shinozakistore@gmail.com/"
        "マイドライブ/AucFanToolData"
    )

    session_name = output_dir.name   # 例: S1_20260508_01_LEDライト
    images_dir   = output_dir / "images"

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

    # ── iPhone用HTML（画像base64埋め込み・オフライン対応） ──
    try:
        html_iphone = _generate_offline_html(dm, images_dir)
        if html_iphone:
            # セッションフォルダに保存
            (output_dir / "result_iphone.html").write_text(html_iphone, encoding="utf-8")
            logger.info(f"自動HTML保存(iPhone用): {output_dir / 'result_iphone.html'}")
            # Google Drive にコピー
            _gdrive_copy_html(
                html_iphone,
                _GDRIVE_DIR / f"{session_name}_iPhone表示用.html",
                label="iPhone表示用"
            )
    except Exception as e:
        logger.error(f"HTML自動保存エラー(iPhone用): {e}")


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


@app.route("/api/export/html")
def api_export_html():
    """スタンドアロンHTMLエクスポート（Mac用・ブラウザで開く用）"""
    from urllib.parse import quote

    dm = get_dm()
    if not dm:
        return jsonify({"error": "データがありません"}), 400

    images_dir = _session_output_dir / "images" if _session_output_dir else None
    html = _generate_export_html(dm, images_dir)
    if not html:
        return jsonify({"error": "商品データがありません"}), 400

    # セッションIDをファイル名に使う（例: S1_20260507_01_バフ_Mac用.html）
    if _session_output_dir:
        session_id = _session_output_dir.name
    else:
        keyword = dm.get_progress().get("keyword", "")
        safe_kw = "".join(c for c in keyword if c.isalnum() or c in ("_", "-"))[:20] or "result"
        session_id = f"aucfan_{safe_kw}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    filename = f"{session_id}_Mac用.html"

    response = Response(html, mimetype="text/html; charset=utf-8")
    response.headers["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(filename)}"
    )
    return response


@app.route("/api/export/html_offline")
def api_export_html_offline():
    """iPhone/iPad向けオフライン自己完結HTMLエクスポート（画像base64埋め込み、モバイル最適化）"""
    from urllib.parse import quote

    dm = get_dm()
    if not dm:
        return jsonify({"error": "データがありません"}), 400

    images_dir = _session_output_dir / "images" if _session_output_dir else None
    # ?filter=active のとき候補・OK・要確認のみ出力（軽量化）
    only_active = request.args.get("filter") == "active"
    html = _generate_offline_html(dm, images_dir, only_active=only_active)
    if not html:
        return jsonify({"error": "商品データがありません"}), 400

    # セッションIDをファイル名に使う（例: S1_20260507_01_バフ_iPhone_iPad用.html）
    if _session_output_dir:
        session_id = _session_output_dir.name
    else:
        keyword = dm.get_progress().get("keyword", "")
        safe_kw = "".join(c for c in keyword if c.isalnum() or c in ("_", "-"))[:20] or "result"
        session_id = f"aucfan_{safe_kw}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    suffix = "_候補のみ" if only_active else ""
    filename = f"{session_id}_iPhone_iPad用{suffix}.html"

    response = Response(html, mimetype="text/html; charset=utf-8")
    response.headers["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(filename)}"
    )
    return response


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


@app.route("/api/export/html_offline_gdrive", methods=["POST"])
def api_export_html_offline_gdrive():
    """
    iPhone/iPad 用オフライン HTML を Google Drive に保存する（サーバーサイド処理）。
    iPhone / Mac どちらからリクエストしても Mac サーバー側で処理するため
    必ず Mac 上の Google Drive フォルダに保存される（ブラウザダウンロードしない）。
    """
    dm = get_dm()
    if not dm:
        # セラー分析セッションも確認
        with _seller_lock:
            dm = _seller_state.get("dm")
        if not dm:
            return jsonify({"success": False, "message": "データがありません"}), 400

    images_dir = _session_output_dir / "images" if _session_output_dir else None

    # リクエストボディの filter フィールドで候補のみ軽量エクスポートに切り替える
    body = request.get_json(silent=True) or {}
    only_active = body.get("filter") == "active"

    html = _generate_offline_html(dm, images_dir, only_active=only_active)
    if not html:
        return jsonify({"success": False, "message": "商品データがありません"}), 400

    # セッション名の取得
    if _session_output_dir:
        session_name = _session_output_dir.name
    else:
        kw = dm.get_progress().get("keyword", "result")
        safe_kw = "".join(c for c in kw if c.isalnum() or c in ("_", "-"))[:20]
        session_name = f"aucfan_{safe_kw}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    suffix = "_候補のみ" if only_active else ""
    gdrive_dir = Path(
        "/Users/shino/Library/CloudStorage/"
        "GoogleDrive-shinozakistore@gmail.com/"
        "マイドライブ/AucFanToolData"
    )
    gdrive_path = gdrive_dir / f"{session_name}_iPhone表示用{suffix}.html"

    # ローカル（セッションフォルダ）にも保存
    local_saved = False
    if _session_output_dir:
        try:
            local_filename = f"result_iphone{suffix}.html"
            (_session_output_dir / local_filename).write_text(html, encoding="utf-8")
            local_saved = True
        except Exception as e:
            logger.warning(f"ローカル保存エラー: {e}")

    # Google Drive に保存
    _gdrive_copy_html(html, gdrive_path, label="iPhone表示用")
    gdrive_saved = gdrive_path.exists()

    return jsonify({
        "success": True,
        "session": session_name,
        "filename": gdrive_path.name,
        "gdrive_saved": gdrive_saved,
        "local_saved": local_saved,
    })


@app.route("/api/export/csv")
def api_export_csv():
    """CSVファイルをダウンロード"""
    dm = get_dm()
    if not dm:
        return jsonify({"error": "データがありません"}), 400

    csv_path = dm.export_csv()
    if not csv_path.exists():
        return jsonify({"error": "CSVファイルが見つかりません"}), 404

    return send_from_directory(
        str(csv_path.parent),
        csv_path.name,
        as_attachment=True,
        download_name=f"aucfan_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mimetype="text/csv; charset=utf-8-sig"
    )


@app.route("/api/load_csv", methods=["POST"])
def api_load_csv():
    """
    results.csv をアップロードしてグリッドに表示する。
    CSV の各行をアイテムとして新規 DataManager セッションにロードし、
    _data_manager を差し替える（画像は別途 /images/ から参照）。
    """
    global _data_manager, _image_processor, _gemini_client, _session_output_dir

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "ファイルがありません"}), 400

    try:
        raw = file.read()
        df = None
        for enc in ("utf-8-sig", "utf-8", "shift-jis"):
            try:
                df = pd.read_csv(io.BytesIO(raw), encoding=enc, dtype=str)
                break
            except Exception:
                continue

        if df is None:
            return jsonify({"error": "CSVの文字コードを判別できませんでした"}), 400
        if df.empty:
            return jsonify({"error": "CSVにデータがありません"}), 400

        # 新規セッションを作成
        keyword_val = "csv_import"
        if "keyword" in df.columns:
            first_kw = str(df["keyword"].iloc[0]).strip()
            if first_kw and first_kw.lower() not in ("nan", ""):
                keyword_val = first_kw

        out_dir, session_id = make_output_dir(keyword_val, step=1)
        dm = DataManager(session_id, out_dir)

        # CSV行をアイテムとして追加
        for _, row in df.iterrows():
            item = {k: v for k, v in row.items() if pd.notna(v)}
            # 数値列を適切な型に変換
            for int_col in ("price", "shipping", "total", "group_size"):
                if int_col in item:
                    try:
                        item[int_col] = int(float(item[int_col]))
                    except (ValueError, TypeError):
                        item[int_col] = 0
            for bool_col in ("needs_review", "scraped_detail"):
                if bool_col in item:
                    item[bool_col] = str(item[bool_col]).lower() in ("true", "1", "yes")
            if isinstance(item.get("images_local"), str):
                # "[]" や JSON文字列をリストに変換
                try:
                    import json as _json
                    item["images_local"] = _json.loads(item["images_local"])
                except Exception:
                    item["images_local"] = []
            dm.add_item(item)

        loaded = dm.total_items
        dm.update_progress(
            keyword=keyword_val,
            status="done",
            total_items=loaded,
        )
        dm.save_all()

        with _lock:
            _data_manager = dm
            _image_processor = ImageProcessor(out_dir / "images")
            _gemini_client = GeminiClient()
            _session_output_dir = out_dir

        logger.info(f"CSV読み込み完了: {file.filename} → {loaded}件 セッション={session_id}")
        return jsonify({
            "success": True,
            "session_id": session_id,
            "total_items": loaded,
            "keyword": keyword_val,
        })

    except Exception as e:
        logger.error(f"CSV読み込みエラー: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# マスターセラーリスト CSV / HTML エクスポート・インポート
# ─────────────────────────────────────────────

@app.route("/api/master_sellers/export/csv")
def api_master_export_csv():
    """マスターセラーリストを CSV でダウンロード"""
    from urllib.parse import quote

    records = _sellers_master.get_all()
    if not records:
        return jsonify({"error": "マスターリストが空です"}), 400

    df = pd.DataFrame(records)
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    buf.seek(0)

    filename = f"sellers_master_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = Response(buf.getvalue(), mimetype="text/csv; charset=utf-8-sig")
    response.headers["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(filename)}"
    )
    return response


@app.route("/api/master_sellers/export/html")
def api_master_export_html():
    """マスターセラーリストをスタンドアロン HTML でダウンロード"""
    from urllib.parse import quote

    records = _sellers_master.get_all()
    if not records:
        return jsonify({"error": "マスターリストが空です"}), 400

    stats = _sellers_master.stats()
    exported_at = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    rows_html = ""
    for r in records:
        scraped = r.get("last_scraped_date") or '<span style="color:#dc2626">未</span>'
        cands = r.get("candidates_count")
        cands_str = str(cands) if cands is not None else "—"
        rows_html += f"""
        <tr>
          <td style="font-family:monospace">{r.get('seller_id', '')}</td>
          <td>{r.get('first_seen_date', '—')}</td>
          <td>{scraped}</td>
          <td style="text-align:center">{cands_str}</td>
          <td>{r.get('source_keyword', '—')}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>マスターセラーリスト</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif;
           font-size: 14px; background: #f9fafb; color: #111827; padding: 16px; }}
    .header {{ background: #2563eb; color: #fff; padding: 12px 16px;
               border-radius: 8px; margin-bottom: 12px; }}
    .header h1 {{ font-size: 16px; font-weight: 700; }}
    .header-meta {{ font-size: 11px; opacity: .8; margin-top: 2px; }}
    .search-bar {{ margin-bottom: 10px; }}
    .search-bar input {{ width: 100%; padding: 8px 12px; border: 1px solid #d1d5db;
                         border-radius: 20px; font-size: 14px; outline: none; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff;
             border-radius: 8px; overflow: hidden;
             box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
    th {{ padding: 10px 12px; background: #f3f4f6; font-weight: 600;
          text-align: left; border-bottom: 2px solid #e5e7eb; font-size: 12px; }}
    td {{ padding: 9px 12px; border-bottom: 1px solid #f3f4f6; font-size: 13px; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #f0f9ff; }}
    .count-info {{ color: #6b7280; font-size: 12px; margin: 8px 0 4px; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>📋 マスターセラーリスト</h1>
    <div class="header-meta">
      合計 {stats['total']}件 ／ 未スクレイピング {stats['unscraped']}件 ／ 書き出し: {exported_at}
    </div>
  </div>
  <div class="search-bar">
    <input type="search" id="searchInput" placeholder="セラーIDで絞り込み..." oninput="filterTable()" autocomplete="off">
  </div>
  <div class="count-info" id="countInfo">表示中: {stats['total']}件</div>
  <table id="masterTable">
    <thead>
      <tr>
        <th>セラーID</th>
        <th>初回検出日</th>
        <th>最終スクレイピング</th>
        <th>候補件数</th>
        <th>キーワード</th>
      </tr>
    </thead>
    <tbody id="tableBody">{rows_html}</tbody>
  </table>
  <script>
    const allRows = Array.from(document.querySelectorAll('#tableBody tr'));
    function filterTable() {{
      const q = document.getElementById('searchInput').value.trim().toLowerCase();
      let count = 0;
      allRows.forEach(tr => {{
        const text = tr.textContent.toLowerCase();
        const show = !q || text.includes(q);
        tr.style.display = show ? '' : 'none';
        if (show) count++;
      }});
      document.getElementById('countInfo').textContent = '表示中: ' + count + '件';
    }}
  </script>
</body>
</html>"""

    filename = f"sellers_master_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    response = Response(html, mimetype="text/html; charset=utf-8")
    response.headers["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quote(filename)}"
    )
    return response


@app.route("/api/master_sellers/import/csv", methods=["POST"])
def api_master_import_csv():
    """
    seller_id 列を含む CSV をアップロードしてマスターリストに追記する。
    既存セラーはスキップ（重複無視）。
    """
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "ファイルがありません"}), 400

    try:
        raw = file.read()
        df = None
        for enc in ("utf-8-sig", "utf-8", "shift-jis"):
            try:
                df = pd.read_csv(io.BytesIO(raw), encoding=enc, dtype=str)
                break
            except Exception:
                continue

        if df is None:
            return jsonify({"error": "CSVの文字コードを判別できませんでした"}), 400
        if "seller_id" not in df.columns:
            return jsonify({"error": "seller_id 列が見つかりません"}), 400

        seller_ids = []
        for _, row in df.iterrows():
            sid = str(row.get("seller_id", "")).strip()
            if sid and sid.lower() not in ("nan", ""):
                seller_ids.append(sid)

        if not seller_ids:
            return jsonify({"error": "有効な seller_id がありません"}), 400

        added = _sellers_master.upsert_sellers(seller_ids, source_keyword="csv_import")

        logger.info(f"マスターリストCSVインポート: {len(seller_ids)}件中 {added}件追加")
        return jsonify({
            "success": True,
            "added": added,
            "total_in_file": len(seller_ids),
            "stats": _sellers_master.stats(),
        })

    except Exception as e:
        logger.error(f"マスターCSVインポートエラー: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/master/merge", methods=["POST"])
def api_master_merge():
    """
    別Macで蓄積した sellers_master.json をアップロードしてマージする。
    seller_id で重複排除し、新しいIDだけを追加する。
    既存データ（first_seen_date等）は上書きしない。
    """
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "ファイルがありません"}), 400

    # 一時ファイルに書き出してから merge_from_file を呼ぶ
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="wb"
        ) as tmp:
            tmp_path = tmp.name
            file.save(tmp)

        result = _sellers_master.merge_from_file(tmp_path)

        logger.info(
            f"マスターリストマージ: {result['added']}件追加、"
            f"{result['skipped']}件スキップ、合計{result['total']}件"
        )
        return jsonify({
            "success": True,
            "added": result["added"],
            "skipped": result["skipped"],
            "total": result["total"],
            "message": (
                f"{result['added']}件追加、"
                f"{result['skipped']}件スキップ（重複）、"
                f"合計{result['total']}件"
            ),
        })

    except (ValueError, FileNotFoundError) as e:
        logger.warning(f"マスターリストマージエラー: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"マスターリストマージ予期せぬエラー: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            import os
            os.unlink(tmp_path)
        except Exception:
            pass


# ─────────────────────────────────────────────
# Chrome タブ一覧取得
# ─────────────────────────────────────────────

@app.route("/api/tabs")
def api_tabs():
    """MacのChromeで開いているAucFanタブ一覧を返す"""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.common.exceptions import WebDriverException

    try:
        options = ChromeOptions()
        options.add_experimental_option(
            "debuggerAddress",
            f"{config.CHROME_DEBUG_HOST}:{config.CHROME_DEBUG_PORT}"
        )
        options.add_argument("--no-sandbox")
        driver = webdriver.Chrome(options=options)

        tabs = []
        current_handle = driver.current_window_handle
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            url   = driver.current_url
            title = driver.title
            tabs.append({
                "handle": handle,
                "url":    url,
                "title":  title,
                "is_aucfan": "aucfan.com" in url,
            })

        # 元のタブに戻す
        try:
            driver.switch_to.window(current_handle)
        except Exception:
            pass

        driver.quit()

        aucfan_tabs = [t for t in tabs if t["is_aucfan"]]
        return jsonify({"tabs": aucfan_tabs, "all_tabs": tabs})

    except WebDriverException:
        return jsonify({"error": "Chromeに接続できません。bash start.sh でアプリを起動してください。", "tabs": []}), 200
    except Exception as e:
        return jsonify({"error": f"エラー: {e}", "tabs": []}), 200


# ─────────────────────────────────────────────
# セッション管理
# ─────────────────────────────────────────────

@app.route("/api/sessions")
def api_sessions():
    """過去のセッション一覧。?step=1|2|3 でフィルタ可能。"""
    step_param = request.args.get("step")
    step_int = int(step_param) if step_param and step_param.isdigit() else None
    return jsonify({"sessions": _list_sessions(step=step_int)})


@app.route("/api/current_session")
def api_current_session():
    """現在グリッドに表示中のセッション情報を返す"""
    if _session_output_dir is None or _data_manager is None:
        return jsonify({"session": None})
    info = _parse_session_info(_session_output_dir.name)
    return jsonify({
        "session": {
            "name": _session_output_dir.name,
            "label": info["label"],
            "date_str": info["date_str"],
            "step": info["step"],
            "total_items": _data_manager.total_items,
            "status": _data_manager.get_progress().get("status", ""),
        }
    })


@app.route("/api/sessions/<session_name>/export_iphone", methods=["POST"])
def api_session_export_iphone(session_name):
    """
    既存セッションの items.json から iPhone 用 HTML を生成して
    セッションフォルダ + Google Drive の両方に保存する。
    現在メモリにロードされているセッションと異なる場合も対応。
    """
    # パストラバーサル防止
    if ".." in session_name or "/" in session_name or "\\" in session_name:
        return jsonify({"success": False, "message": "不正なセッション名"}), 400

    base = Path(config.OUTPUT_BASE_DIR)
    session_dir = base / session_name
    if not session_dir.exists():
        return jsonify({"success": False, "message": "セッションが見つかりません"}), 404

    items_file = session_dir / "items.json"
    if not items_file.exists():
        return jsonify({"success": False, "message": "items.json が見つかりません"}), 404

    try:
        # 一時的に DataManager を作成してデータをロード
        tmp_dm = DataManager(session_name, session_dir)
        tmp_dm.load_previous_session()

        if tmp_dm.total_items == 0:
            return jsonify({"success": False, "message": "商品データが空です"}), 400

        images_dir = session_dir / "images"

        # iPhone 用 HTML 生成（base64 画像埋め込み）
        html_iphone = _generate_offline_html(tmp_dm, images_dir)
        if not html_iphone:
            return jsonify({"success": False, "message": "HTML生成に失敗しました"}), 500

        # セッションフォルダに保存
        local_path = session_dir / "result_iphone.html"
        local_path.write_text(html_iphone, encoding="utf-8")
        logger.info(f"iPhone用HTML保存: {local_path}")

        # Google Drive に保存
        gdrive_dir = Path(
            "/Users/shino/Library/CloudStorage/"
            "GoogleDrive-shinozakistore@gmail.com/"
            "マイドライブ/AucFanToolData"
        )
        gdrive_path = gdrive_dir / f"{session_name}_iPhone表示用.html"
        _gdrive_copy_html(html_iphone, gdrive_path, label="iPhone表示用")

        gdrive_saved = gdrive_path.exists()

        return jsonify({
            "success": True,
            "session": session_name,
            "total_items": tmp_dm.total_items,
            "local_path": str(local_path),
            "gdrive_path": str(gdrive_path) if gdrive_saved else None,
            "gdrive_saved": gdrive_saved,
        })

    except Exception as e:
        logger.error(f"iPhone用HTML生成エラー ({session_name}): {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/sessions/<session_name>", methods=["DELETE"])
def api_delete_session(session_name):
    """
    セッションフォルダを丸ごと削除する。
    現在メモリにロードされているセッションを削除する場合は _data_manager もリセット。
    """
    global _data_manager, _image_processor, _gemini_client, _session_output_dir

    # パストラバーサル防止
    if ".." in session_name or "/" in session_name or "\\" in session_name:
        return jsonify({"success": False, "message": "不正なセッション名"}), 400

    base = Path(config.OUTPUT_BASE_DIR)
    session_dir = base / session_name

    if not session_dir.exists():
        return jsonify({"success": False, "message": "セッションが見つかりません"}), 404

    try:
        shutil.rmtree(session_dir)
        logger.info(f"セッション削除: {session_dir}")

        # 削除したセッションが現在ロード中なら状態をリセット
        if _session_output_dir is not None and _session_output_dir.resolve() == session_dir.resolve():
            _data_manager = None
            _image_processor = None
            _gemini_client = None
            _session_output_dir = None
            logger.info("現在のセッションを削除したためメモリをリセットしました")

        return jsonify({"success": True, "name": session_name})
    except Exception as e:
        logger.error(f"セッション削除エラー: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/sessions/<session_name>/seller_ids", methods=["POST"])
def api_seller_ids_from_session(session_name):
    """
    指定した過去のSTEP 1セッションの results.csv から seller_id を抽出して
    _seller_state にセットする。
    """
    # パストラバーサル防止
    if ".." in session_name or "/" in session_name or "\\" in session_name:
        return jsonify({"error": "不正なセッション名"}), 400

    base = Path(config.OUTPUT_BASE_DIR)
    session_dir = base / session_name
    csv_path = session_dir / "results.csv"

    if not csv_path.exists():
        # CSV がなければ items.json から試みる
        items_path = session_dir / "items.json"
        if items_path.exists():
            try:
                with open(items_path, encoding="utf-8") as f:
                    items_dict = json.load(f)
                seen = {}
                for item in items_dict.values():
                    sid = str(item.get("seller_id", "")).strip()
                    if not sid or sid.lower() in ("nan", ""):
                        continue
                    if sid not in seen:
                        url = str(item.get("seller_url", "")).strip()
                        seen[sid] = "" if url.lower() in ("nan", "") else url
                sellers = [{"seller_id": s, "seller_url": u, "status": "pending"} for s, u in seen.items()]
                with _seller_lock:
                    _seller_state["sellers"] = sellers
                    _seller_state["current_index"] = -1
                    _seller_state["running"] = False
                    _seller_state["stop_requested"] = False
                    _seller_state["session_dirs"] = []
                return jsonify({
                    "count": len(sellers),
                    "has_seller_url": any(s["seller_url"] for s in sellers),
                    "sellers": sellers,
                    "session_name": session_name,
                })
            except Exception as e:
                return jsonify({"error": f"items.json 読み込み失敗: {e}"}), 500
        return jsonify({"error": f"results.csv が見つかりません: {session_name}"}), 404

    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
        if "seller_id" not in df.columns:
            return jsonify({"error": "seller_id 列が見つかりません"}), 400

        has_seller_url = "seller_url" in df.columns
        seen = {}
        for _, row in df.iterrows():
            sid = str(row.get("seller_id", "")).strip()
            if not sid or sid.lower() in ("nan", ""):
                continue
            if sid not in seen:
                seller_url = ""
                if has_seller_url:
                    u = str(row.get("seller_url", "")).strip()
                    if u and u.lower() != "nan":
                        seller_url = u
                seen[sid] = seller_url

        sellers = [{"seller_id": s, "seller_url": u, "status": "pending"} for s, u in seen.items()]

        with _seller_lock:
            _seller_state["sellers"] = sellers
            _seller_state["current_index"] = -1
            _seller_state["running"] = False
            _seller_state["stop_requested"] = False
            _seller_state["session_dirs"] = []

        logger.info(f"セッション({session_name})からセラーID抽出: {len(sellers)}件")
        return jsonify({
            "count": len(sellers),
            "has_seller_url": has_seller_url,
            "sellers": sellers,
            "session_name": session_name,
        })
    except Exception as e:
        logger.error(f"セラーID抽出エラー: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_name>/load", methods=["POST"])
def api_load_session(session_name):
    """過去セッションをロード"""
    global _data_manager, _image_processor, _gemini_client, _session_output_dir

    base = Path(config.OUTPUT_BASE_DIR)
    session_dir = base / session_name

    if not session_dir.exists():
        return jsonify({"success": False, "message": "セッションが見つかりません"}), 404

    _session_output_dir = session_dir
    _data_manager = DataManager(session_name, session_dir)
    _data_manager.load_previous_session()
    _image_processor = ImageProcessor(session_dir / "images")
    _gemini_client = GeminiClient()

    return jsonify({
        "success": True,
        "session": session_name,
        "total_items": _data_manager.total_items,
    })


def _parse_session_info(name: str) -> dict:
    """フォルダ名から表示用情報を解析する（新旧両命名規則対応）。"""
    import re

    # 新命名規則: S1_20260506_01_バフ / S2_20260506_01 / S3_20260506_01
    m = re.match(r'^S(\d)_(\d{4})(\d{2})(\d{2})_(\d+)(?:_(.+))?$', name)
    if m:
        s, y, mo, d, num, kw = m.groups()
        step = int(s)
        st_map = {1: "keyword", 2: "seller", 3: "master"}
        lbl_map = {1: "STEP 1", 2: "セラー分析", 3: "マスター分析"}
        label = kw if (step == 1 and kw) else lbl_map.get(step, f"STEP {s}")
        return {
            "step": step,
            "session_type": st_map.get(step, "keyword"),
            "label": label,
            "date_str": f"{y}/{mo}/{d}",
            "num": int(num),
        }

    # 旧命名規則: keyword_YYYYMMDD_HHMMSS
    m = re.match(r'^(.+?)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})\d{2}$', name)
    if m:
        kw, y, mo, d, h, mi = m.groups()
        if kw.startswith("seller_analysis"):
            step, st, label = 2, "seller", "セラー分析"
        elif kw.startswith("master_analysis"):
            step, st, label = 3, "master", "マスター分析"
        else:
            step, st, label = 1, "keyword", kw
        return {
            "step": step,
            "session_type": st,
            "label": label,
            "date_str": f"{y}/{mo}/{d} {h}:{mi}",
            "num": 0,
        }

    return {"step": 1, "session_type": "keyword", "label": name, "date_str": "", "num": 0}


def _list_sessions(step: int = None):
    """過去セッションの一覧を返す。step を指定するとそのステップのみ返す。"""
    base = Path(config.OUTPUT_BASE_DIR)
    # Google Drive 未接続の場合はローカルフォールバック
    if not base.exists():
        _gdrive_prefix = os.path.expanduser("~/Library/CloudStorage/")
        if str(base).startswith(_gdrive_prefix):
            base = Path("リサーチ結果")
    if not base.exists():
        return []

    # 現在スクレイピング中のセッション名（is_running フラグ用）
    running_names: set = set()
    if _scraper_thread and _scraper_thread.is_alive() and _session_output_dir:
        running_names.add(_session_output_dir.name)
    with _seller_lock:
        if _seller_state["running"] and _seller_state.get("output_dir"):
            running_names.add(Path(_seller_state["output_dir"]).name)
    with _master_lock:
        if _master_state["running"] and _master_state.get("output_dir"):
            running_names.add(Path(_master_state["output_dir"]).name)

    sessions = []
    for d in sorted(base.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        info = _parse_session_info(d.name)
        if step is not None and info["step"] != step:
            continue

        # progress.json も results.csv もない空フォルダはリストに出さない
        # （削除後にGoogleDriveの同期で空フォルダが残る場合などに対応）
        progress_file = d / "progress.json"
        has_data = progress_file.exists() or (d / "results.csv").exists() or (d / "items.json").exists()
        if not has_data:
            continue

        p = {}
        if progress_file.exists():
            try:
                with open(progress_file) as f:
                    p = json.load(f)
            except Exception:
                pass

        sessions.append({
            "name": d.name,
            "step": info["step"],
            "session_type": info["session_type"],   # 後方互換
            "label": info["label"],
            "date_str": info["date_str"],
            "num": info["num"],
            "keyword": p.get("keyword", info["label"]),
            "status": p.get("status", "unknown"),
            "total_items": p.get("total_items", 0),
            "started_at": p.get("started_at", ""),
            "updated_at": p.get("updated_at", ""),
            "has_csv": (d / "results.csv").exists(),
            "is_running": d.name in running_names,
        })

    return sessions[:100]


# ─────────────────────────────────────────────
# レポート API
# ─────────────────────────────────────────────

@app.route("/api/report")
def api_report():
    """セラー分析・画像グループ分析レポートを返す"""
    dm = get_dm()
    if not dm:
        return jsonify({"error": "データがありません"}), 400

    items = dm.get_all_items()
    if not items:
        return jsonify({"error": "商品データがありません"}), 400

    from collections import defaultdict

    # ── セラーごとの集計 ──
    seller_items = defaultdict(list)   # seller_id -> [item, ...]
    seller_groups = defaultdict(set)   # seller_id -> {group_id, ...}

    for item in items:
        sid = item.get("seller_id", "").strip()
        if not sid:
            continue
        gid = item.get("group_id") or item.get("item_id", "")
        seller_items[sid].append(item)
        seller_groups[sid].add(gid)

    seller_ranking = []
    for sid, sitems in seller_items.items():
        prices = [i.get("price", 0) for i in sitems if i.get("price", 0) > 0]
        seller_ranking.append({
            "seller_id": sid,
            "item_count": len(sitems),
            "group_count": len(seller_groups[sid]),
            "min_price": min(prices) if prices else 0,
            "max_price": max(prices) if prices else 0,
        })
    seller_ranking.sort(key=lambda x: x["item_count"], reverse=True)

    # ── グループごとの集計 ──
    group_map = defaultdict(list)
    for item in items:
        gid = item.get("group_id") or item.get("item_id", "")
        group_map[gid].append(item)

    group_report = []
    for gid, gitems in group_map.items():
        prices = [i.get("price", 0) for i in gitems if i.get("price", 0) > 0]
        sellers = [i.get("seller_id", "").strip() for i in gitems if i.get("seller_id", "").strip()]
        seller_counter = defaultdict(int)
        for s in sellers:
            seller_counter[s] += 1
        unique_sellers = list(seller_counter.keys())
        dup_sellers = [s for s, c in seller_counter.items() if c > 1]

        title = (gitems[0].get("title_full") or gitems[0].get("title_short", ""))[:60]
        thumb = gitems[0].get("thumbnail_local", "")
        thumb_name = Path(thumb).name if thumb else ""

        # グループが大きすぎる場合はpHashの誤グループ化の可能性あり
        too_large = len(gitems) > 50

        group_report.append({
            "group_id": gid,
            "title": title,
            "item_count": len(gitems),
            "seller_count": len(unique_sellers),
            "sellers": unique_sellers[:10],
            "dup_sellers": dup_sellers,
            "min_price": min(prices) if prices else 0,
            "max_price": max(prices) if prices else 0,
            "status": gitems[0].get("status", ""),
            "thumbnail": thumb_name,
            "too_large": too_large,
        })
    group_report.sort(key=lambda x: x["item_count"], reverse=True)

    # ── 同一セラー×同一グループ（自演出品候補） ──
    suspicious = []
    for gr in group_report:
        if gr["dup_sellers"]:
            suspicious.append({
                "group_id": gr["group_id"],
                "title": gr["title"],
                "dup_sellers": gr["dup_sellers"],
                "item_count": gr["item_count"],
            })

    return jsonify({
        "seller_ranking": seller_ranking[:50],
        "group_report": group_report[:100],
        "suspicious": suspicious,
        "total_items": len(items),
        "total_sellers": len(seller_ranking),
        "total_groups": len(group_report),
    })


# ─────────────────────────────────────────────
# セラー分析機能
# ─────────────────────────────────────────────

@app.route("/api/seller_ids_from_current_session", methods=["POST"])
def api_seller_ids_from_current_session():
    """
    現在メモリに読み込まれているキーワードリサーチ結果から
    seller_id のユニークリストを抽出して _seller_state にセットする。
    CSV ファイルを介さずに STEP 1 → STEP 2 を直結する。
    """
    dm = get_dm()
    if dm is None or dm.total_items == 0:
        return jsonify({"error": "現在のセッションにデータがありません。先にSTEP 1のスクレイピングを実行してください"}), 404

    all_items = dm.get_all_items()
    seen = {}
    for item in all_items:
        sid = str(item.get("seller_id", "")).strip()
        if not sid or sid.lower() in ("nan", ""):
            continue
        if sid not in seen:
            seller_url = str(item.get("seller_url", "")).strip()
            if seller_url.lower() in ("nan", ""):
                seller_url = ""
            seen[sid] = seller_url

    if not seen:
        return jsonify({"error": "seller_id が見つかりませんでした（スクレイピング結果を確認してください）"}), 404

    sellers = [
        {"seller_id": sid, "seller_url": url, "status": "pending"}
        for sid, url in seen.items()
    ]

    with _seller_lock:
        _seller_state["sellers"] = sellers
        _seller_state["current_index"] = -1
        _seller_state["running"] = False
        _seller_state["stop_requested"] = False
        _seller_state["session_dirs"] = []

    has_seller_url = any(s["seller_url"] for s in sellers)
    keyword = dm.get_progress().get("keyword", "（不明）")
    logger.info(f"現在のセッション({keyword})からセラーID抽出: {len(sellers)}件")

    return jsonify({
        "count": len(sellers),
        "has_seller_url": has_seller_url,
        "sellers": sellers,
        "keyword": keyword,
    })


@app.route("/api/latest_csv_import", methods=["POST"])
def api_latest_csv_import():
    """
    Mac上の最新 results.csv を自動で読み込む（iPhone からのアップロード不要）。
    現在アクティブなセッション → なければ最新セッションの順で探す。
    """
    csv_path = None
    session_name = ""

    # 1. 現在アクティブなセッションの CSV を優先
    if _session_output_dir is not None:
        candidate = _session_output_dir / "results.csv"
        if candidate.exists():
            csv_path = candidate
            session_name = _session_output_dir.name

    # 2. なければ最新セッションを探す
    if csv_path is None:
        base = Path(config.OUTPUT_BASE_DIR)
        if base.exists():
            for d in sorted(base.iterdir(), reverse=True):
                if d.is_dir():
                    candidate = d / "results.csv"
                    if candidate.exists():
                        csv_path = candidate
                        session_name = d.name
                        break

    if csv_path is None:
        return jsonify({"error": "results.csv が見つかりません。先にキーワードスクレイピングを実行してください"}), 404

    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)

        if "seller_id" not in df.columns:
            return jsonify({"error": f"seller_id 列が見つかりません: {csv_path}"}), 400

        has_seller_url = "seller_url" in df.columns

        seen = {}
        for _, row in df.iterrows():
            sid = str(row.get("seller_id", "")).strip()
            if not sid or sid.lower() == "nan":
                continue
            if sid not in seen:
                seller_url = ""
                if has_seller_url:
                    u = str(row.get("seller_url", "")).strip()
                    if u and u.lower() != "nan":
                        seller_url = u
                seen[sid] = seller_url

        sellers = [
            {"seller_id": sid, "seller_url": url, "status": "pending"}
            for sid, url in seen.items()
        ]

        with _seller_lock:
            _seller_state["sellers"] = sellers
            _seller_state["current_index"] = -1
            _seller_state["running"] = False
            _seller_state["stop_requested"] = False
            _seller_state["session_dirs"] = []

        logger.info(f"最新CSV自動読み込み: {csv_path} → {len(sellers)}件のユニークセラー")
        return jsonify({
            "count": len(sellers),
            "has_seller_url": has_seller_url,
            "sellers": sellers,
            "session_name": session_name,
            "csv_path": str(csv_path),
        })

    except Exception as e:
        logger.error(f"最新CSV読み込みエラー: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/import_csv", methods=["POST"])
def api_import_csv():
    """
    CSVをアップロードしてseller_idを抽出する。
    CSVフォーマット: results.csv と同一（seller_id列必須、seller_url列は任意）
    """
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "ファイルがありません"}), 400

    try:
        raw = file.read()
        # UTF-8 BOM → UTF-8 → Shift-JIS の順で試す
        for enc in ("utf-8-sig", "utf-8", "shift-jis"):
            try:
                df = pd.read_csv(io.BytesIO(raw), encoding=enc, dtype=str)
                break
            except Exception:
                continue
        else:
            return jsonify({"error": "CSVの文字コードを判別できませんでした"}), 400

        if "seller_id" not in df.columns:
            return jsonify({"error": "seller_id 列が見つかりません"}), 400

        has_seller_url = "seller_url" in df.columns

        # ユニークセラーを抽出（最初に出現した seller_url を使う）
        seen = {}
        for _, row in df.iterrows():
            sid = str(row.get("seller_id", "")).strip()
            if not sid or sid.lower() == "nan":
                continue
            if sid not in seen:
                seller_url = ""
                if has_seller_url:
                    u = str(row.get("seller_url", "")).strip()
                    if u and u.lower() != "nan":
                        seller_url = u
                seen[sid] = seller_url

        sellers = [
            {"seller_id": sid, "seller_url": url, "status": "pending"}
            for sid, url in seen.items()
        ]

        with _seller_lock:
            _seller_state["sellers"] = sellers
            _seller_state["current_index"] = -1
            _seller_state["running"] = False
            _seller_state["stop_requested"] = False
            _seller_state["session_dirs"] = []

        logger.info(f"CSVインポート完了: {len(sellers)}件のユニークセラー（seller_url={'あり' if has_seller_url else 'なし'}）")
        return jsonify({
            "count": len(sellers),
            "has_seller_url": has_seller_url,
            "sellers": sellers,
        })

    except Exception as e:
        logger.error(f"CSVインポートエラー: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/seller_scrape/start", methods=["POST"])
def api_seller_scrape_start():
    """セラー分析スクレイピングを開始"""
    with _seller_lock:
        if _seller_state["running"]:
            return jsonify({"error": "既に実行中です"}), 400
        sellers = _seller_state["sellers"]
        if not sellers:
            return jsonify({"error": "セラーリストがありません。先にCSVをインポートしてください"}), 400

        stop_ev = threading.Event()
        _seller_state["running"] = True
        _seller_state["phase"] = "scraping_list"
        _seller_state["stop_event"] = stop_ev
        _seller_state["session_id"] = None
        _seller_state["output_dir"] = None
        _seller_state["dm"] = None

    t = threading.Thread(
        target=_run_seller_analysis,
        args=(stop_ev,),
        daemon=True,
        name="seller-analyzer",
    )
    t.start()
    with _seller_lock:
        _seller_state["thread"] = t

    logger.info(f"セラー分析スクレイピング開始: {len(sellers)}件")
    return jsonify({"status": "started", "total": len(sellers)})


def _run_seller_analysis(stop_ev: threading.Event):
    """
    SellerAnalyzer を使って全セラーを 1 セッションにまとめてスクレイプする
    バックグラウンドスレッド。完了後に _data_manager を差し替えてメイン UI で表示可能にする。
    """
    global _data_manager, _image_processor, _gemini_client, _session_output_dir

    with _seller_lock:
        sellers = list(_seller_state["sellers"])

    # 1 セッションフォルダを作成 (S2_YYYYMMDD_NN)
    out_dir, session_id = make_output_dir("seller_analysis", step=2)
    dm = DataManager(session_id, out_dir)
    img = ImageProcessor(out_dir / "images")
    gc = GeminiClient()

    with _seller_lock:
        _seller_state["session_id"] = session_id
        _seller_state["output_dir"] = out_dir
        _seller_state["dm"] = dm

    # セラーごとの進捗をコールバックで _seller_state に反映
    def on_progress(index: int, status: str, extra: dict = None):
        with _seller_lock:
            if 0 <= index < len(_seller_state["sellers"]):
                _seller_state["sellers"][index]["status"] = status
                # used_skip 時などに追加情報（used_count 等）を保存
                if extra:
                    _seller_state["sellers"][index].update(extra)
            _seller_state["current_index"] = index if status == "running" else -1
            # phase を DataManager の進捗から同期
            dm_status = dm.get_progress().get("status", "scraping_list")
            _seller_state["phase"] = dm_status

    analyzer = SellerAnalyzer(
        sellers=sellers,
        data_manager=dm,
        image_processor=img,
        gemini_client=gc,
        stop_event=stop_ev,
        on_seller_progress=on_progress,
    )
    analyzer.run()

    final_status = dm.get_progress().get("status", "done")

    # CSV・HTML を自動保存（完了時のみ）
    if final_status in ("done", "stopped"):
        _save_export_files(dm, out_dir)

    # 完了後: メイン UI でそのまま結果を表示できるよう差し替え
    with _lock:
        _data_manager = dm
        _image_processor = img
        _gemini_client = gc
        _session_output_dir = out_dir

    with _seller_lock:
        _seller_state["running"] = False
        _seller_state["current_index"] = -1
        _seller_state["phase"] = final_status

    logger.info("=" * 50)
    logger.info(f"=== STEP 2 スクレイピング完了 === 全{dm.total_items}件処理 ({final_status})")
    logger.info("=" * 50)
    logger.info(">>> 待機中 (アプリは起動中) <<<  次の操作をブラウザから行ってください")


@app.route("/api/seller_scrape/stop", methods=["POST"])
def api_seller_scrape_stop():
    """セラー分析スクレイピングを停止"""
    with _seller_lock:
        ev = _seller_state.get("stop_event")
    if ev:
        ev.set()
    logger.info("セラー分析停止リクエスト")
    return jsonify({"status": "stopping"})


@app.route("/api/seller_scrape/status")
def api_seller_scrape_status():
    """セラー分析スクレイピングの現在状態を返す"""
    with _seller_lock:
        sellers = list(_seller_state["sellers"])
        current_index = _seller_state["current_index"]
        running = _seller_state["running"]
        phase = _seller_state["phase"]
        session_id = _seller_state["session_id"]
        dm = _seller_state["dm"]

    total = len(sellers)
    done_sellers = sum(1 for s in sellers if s.get("status") == "done")
    errors = sum(1 for s in sellers if s.get("status") == "error")
    used_skipped = sum(1 for s in sellers if s.get("status") == "used_skip")

    # DataManager から詳細進捗を取得
    dm_progress = {}
    total_items = 0
    if dm is not None:
        try:
            dm_progress = dm.get_progress()
            total_items = dm.total_items
        except Exception:
            pass

    return jsonify({
        "running": running,
        "phase": phase,
        "current_index": current_index,
        "total": total,
        "done": done_sellers,
        "errors": errors,
        "used_skipped": used_skipped,
        "sellers": sellers,
        "session_id": session_id,
        "total_items": total_items,
        "detail_pages_done": dm_progress.get("detail_pages_done", 0),
        "detail_pages_total": dm_progress.get("detail_pages_total", 0),
    })


@app.route("/api/seller_scrape/reset", methods=["POST"])
def api_seller_scrape_reset():
    """セラーリストをリセット"""
    with _seller_lock:
        if _seller_state["running"]:
            return jsonify({"error": "実行中はリセットできません"}), 400
        _seller_state["sellers"] = []
        _seller_state["current_index"] = -1
        _seller_state["phase"] = "idle"
        _seller_state["stop_event"] = None
        _seller_state["dm"] = None
        _seller_state["session_id"] = None
        _seller_state["output_dir"] = None
    return jsonify({"status": "reset"})


# ─────────────────────────────────────────────
# STEP 3: マスターセラーリサーチ
# ─────────────────────────────────────────────

@app.route("/api/master_sellers")
def api_master_sellers():
    """マスターセラーリスト取得（ソート・件数制限付き）"""
    sort_order = request.args.get("sort_order", "desc")   # asc / desc
    limit = request.args.get("limit", "0")
    try:
        limit = int(limit)
    except ValueError:
        limit = 0
    records = _sellers_master.get_all(sort_order=sort_order)
    if limit > 0:
        records = records[:limit]
    return jsonify({"sellers": records, "total": len(records)})


@app.route("/api/master_sellers/stats")
def api_master_sellers_stats():
    """マスターリスト統計"""
    return jsonify(_sellers_master.stats())


@app.route("/api/master_sellers/scrape/start", methods=["POST"])
def api_master_scrape_start():
    """STEP 3 スクレイピング開始"""
    with _master_lock:
        if _master_state["running"]:
            return jsonify({"error": "既に実行中です"}), 400

    data = request.get_json(silent=True) or {}
    sort_order = data.get("sort_order", "desc")
    batch_size = data.get("batch_size", 0)   # 0 = 上限なし

    all_unscraped = _sellers_master.get_unscraped(sort_order=sort_order)
    if not all_unscraped:
        return jsonify({"error": "未スクレイピングのセラーがありません"}), 400

    targets = all_unscraped[:batch_size] if batch_size > 0 else all_unscraped

    stop_ev = threading.Event()
    with _master_lock:
        _master_state["running"] = True
        _master_state["phase"] = "scraping_list"
        _master_state["stop_event"] = stop_ev
        _master_state["session_id"] = None
        _master_state["output_dir"] = None
        _master_state["dm"] = None
        _master_state["total"] = len(targets)
        _master_state["done"] = 0
        _master_state["current_seller"] = ""

    t = threading.Thread(
        target=_run_master_analysis,
        args=(targets, stop_ev),
        daemon=True,
        name="master-analyzer",
    )
    t.start()
    with _master_lock:
        _master_state["thread"] = t

    logger.info(f"STEP 3 スクレイピング開始: {len(targets)}件")
    return jsonify({"status": "started", "total": len(targets)})


@app.route("/api/master_sellers/scrape/stop", methods=["POST"])
def api_master_scrape_stop():
    """STEP 3 スクレイピング停止"""
    with _master_lock:
        ev = _master_state.get("stop_event")
    if ev:
        ev.set()
    logger.info("STEP 3 停止リクエスト")
    return jsonify({"status": "stopping"})


@app.route("/api/master_sellers/scrape/status")
def api_master_scrape_status():
    """STEP 3 進捗"""
    with _master_lock:
        running = _master_state["running"]
        phase = _master_state["phase"]
        total = _master_state["total"]
        done = _master_state["done"]
        current_seller = _master_state["current_seller"]
        session_id = _master_state["session_id"]
        dm = _master_state["dm"]

    total_items = 0
    processed_items = 0
    if dm is not None:
        try:
            total_items = dm.total_items
            processed_items = dm.get_progress().get("processed_items", total_items)
        except Exception:
            pass

    return jsonify({
        "running": running,
        "phase": phase,
        "total": total,
        "done": done,
        "current_seller": current_seller,
        "session_id": session_id,
        "total_items": total_items,
        "processed_items": processed_items,
    })


@app.route("/api/master_sellers/all", methods=["DELETE"])
def api_master_delete_all():
    """マスターリスト全件削除"""
    deleted = _sellers_master.clear_all()
    logger.info(f"マスターリスト全削除: {deleted}件")
    return jsonify({"success": True, "deleted": deleted})


@app.route("/api/master_sellers/<seller_id>", methods=["DELETE"])
def api_master_delete_seller(seller_id):
    """個別セラー削除"""
    ok = _sellers_master.delete_seller(seller_id)
    if not ok:
        return jsonify({"success": False, "error": "seller_id が見つかりません"}), 404
    return jsonify({"success": True, "seller_id": seller_id})


def _run_master_analysis(targets: list, stop_ev: threading.Event):
    """STEP 3 バックグラウンドスレッド"""
    global _data_manager, _image_processor, _gemini_client, _session_output_dir

    out_dir, session_id = make_output_dir("master_analysis", step=3)
    dm = DataManager(session_id, out_dir)
    img = ImageProcessor(out_dir / "images")
    gc = GeminiClient()

    with _master_lock:
        _master_state["session_id"] = session_id
        _master_state["output_dir"] = out_dir
        _master_state["dm"] = dm

    # SellerAnalyzer に渡す形式に変換
    sellers_for_analyzer = [
        {
            "seller_id": r["seller_id"],
            "seller_url": f"https://aucfan.com/search1/?aucnm={r['seller_id']}",
            "status": "pending",
        }
        for r in targets
    ]

    def on_progress(index: int, status: str):
        with _master_lock:
            sid = targets[index]["seller_id"] if 0 <= index < len(targets) else ""
            if status == "running":
                _master_state["current_seller"] = sid
            if status == "done":
                _master_state["done"] += 1
                # last_scraped_date と candidates_count を書き戻す
                try:
                    # 完了時点でのグループ化済み候補数を取得
                    cnt = sum(
                        1 for i in dm.get_all_items()
                        if i.get("seller_id") == sid
                        and i.get("status") in (
                            config.STATUS_CANDIDATE,
                            config.STATUS_NEXT_CANDIDATE,
                            config.STATUS_OK,
                        )
                    )
                    _sellers_master.update_scraped(sid, candidates_count=cnt)
                except Exception as _e:
                    logger.warning(f"sellers_master 更新失敗 ({sid}): {_e}")
            dm_status = dm.get_progress().get("status", "scraping_list")
            _master_state["phase"] = dm_status

    analyzer = SellerAnalyzer(
        sellers=sellers_for_analyzer,
        data_manager=dm,
        image_processor=img,
        gemini_client=gc,
        stop_event=stop_ev,
        on_seller_progress=on_progress,
    )
    analyzer.run()

    final_status = dm.get_progress().get("status", "done")
    if final_status in ("done", "stopped"):
        _save_export_files(dm, out_dir)

    # 完了後にメイン UI に差し替え
    with _lock:
        _data_manager = dm
        _image_processor = img
        _gemini_client = gc
        _session_output_dir = out_dir

    with _master_lock:
        _master_state["running"] = False
        _master_state["current_seller"] = ""
        _master_state["phase"] = final_status

    logger.info("=" * 50)
    logger.info(f"=== STEP 3 スクレイピング完了 === 全{dm.total_items}件処理 ({final_status})")
    logger.info("=" * 50)


# ─────────────────────────────────────────────
# Gemini レート制限ステータス API
# ─────────────────────────────────────────────

@app.route("/api/gemini_status")
def api_gemini_status():
    """Gemini API エラーフラグの現在状態を返す
    Response: {"rate_limit_hit": bool, "type": str|null, "time": str|null}
    """
    status = get_rate_limit_status()
    return jsonify({
        "rate_limit_hit": status["rate_limit_hit"],
        "type": status["type"],
        "time": status["time"],
    })


@app.route("/api/gemini_status/reset", methods=["POST"])
def api_gemini_status_reset():
    """Gemini API エラーフラグをリセットする"""
    reset_rate_limit_flag()
    return jsonify({"success": True})


# ─────────────────────────────────────────────
# エラーハンドラー
# ─────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not Found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# 起動
# ─────────────────────────────────────────────

def check_env():
    """起動前チェック"""
    issues = []

    if not config.GEMINI_API_KEY:
        issues.append("⚠️  GEMINI_API_KEY が未設定です（.env ファイルを確認）。pHashのみで動作します。")

    for issue in issues:
        logger.warning(issue)

    logger.info("=" * 60)
    logger.info("  AucFan リサーチツール")
    logger.info("=" * 60)
    logger.info(f"  Flask URL  : http://{config.FLASK_HOST}:{config.FLASK_PORT}")
    logger.info(f"  Chrome接続 : {config.CHROME_DEBUG_HOST}:{config.CHROME_DEBUG_PORT}")
    logger.info(f"  出力先     : {config.OUTPUT_BASE_DIR}/")
    logger.info(f"  Gemini     : {'有効' if config.GEMINI_ENABLED and config.GEMINI_API_KEY else '無効'}")
    logger.info("=" * 60)
    logger.info("")
    logger.info("使い方:")
    logger.info("  1. AucFanで検索条件を設定し1ページ目を表示した状態にする")
    logger.info(f"  2. ブラウザで http://localhost:{config.FLASK_PORT} を開く（自動で開きます）")
    logger.info("  3. UIでキーワードを入力して「スクレイピング開始」をクリック")
    logger.info("")


def _auto_load_latest_session():
    """
    起動時に最新のセッションを自動ロードする。
    前回のスクレイピング結果をすぐに表示できるようにする。
    セッションが存在しない場合は何もしない。
    """
    global _data_manager, _image_processor, _gemini_client, _session_output_dir

    base = Path(config.OUTPUT_BASE_DIR)
    if not base.exists():
        return

    # 最新のセッションフォルダを探す（更新日時順）
    latest_dir = None
    for d in sorted(base.iterdir(), reverse=True):
        if d.is_dir() and (d / "progress.json").exists():
            latest_dir = d
            break

    if latest_dir is None:
        return

    try:
        session_name = latest_dir.name
        _session_output_dir = latest_dir
        _data_manager = DataManager(session_name, latest_dir)
        _data_manager.load_previous_session()
        _image_processor = ImageProcessor(latest_dir / "images")
        _gemini_client = GeminiClient()
        logger.info(
            f"[起動時自動ロード] セッション: {session_name}"
            f" ({_data_manager.total_items}件)"
        )
    except Exception as e:
        logger.warning(f"[起動時自動ロード] 失敗（スキップ）: {e}")
        # ロード失敗してもFlaskは起動する


if __name__ == "__main__":
    check_env()

    # 最新セッションをバックグラウンドで自動ロード（Google Drive 同期中でもFlaskをすぐ起動するため）
    auto_load_thread = threading.Thread(target=_auto_load_latest_session, daemon=True)
    auto_load_thread.start()

    # ブラウザを自動で開く（少し遅らせる）
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{config.FLASK_PORT}")

    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()

    # Flask 起動（スレッド化されたSSEのため use_reloader=False）
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
