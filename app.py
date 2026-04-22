"""
app.py - AucFan リサーチツール メインエントリーポイント
- Flask Webアプリ起動
- Seleniumスクレイパーをバックグラウンドスレッドで実行
- リアルタイム進捗をSSEで配信
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

from flask import (
    Flask, Response, jsonify, render_template, request,
    send_from_directory, abort
)

import config
from data_manager import DataManager, make_output_dir, make_session_id
from image_processor import ImageProcessor
from gemini_client import GeminiClient
from scraper import AucFanScraper

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

# ─────────────────────────────────────────────
# Flask アプリ
# ─────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.urandom(24)

# グローバル状態
_scraper_thread: threading.Thread = None
_stop_event = threading.Event()
_data_manager: DataManager = None
_image_processor: ImageProcessor = None
_gemini_client: GeminiClient = None
_session_output_dir: Path = None
_lock = threading.Lock()


def get_dm() -> DataManager:
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
        keyword = data.get("keyword", "unknown")
        resume = data.get("resume", False)

        # セッション初期化
        out_dir, session_id = make_output_dir(keyword)
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
            scraper.run(resume=resume)

        _scraper_thread = threading.Thread(target=run_scraper, daemon=True, name="scraper")
        _scraper_thread.start()

        logger.info(f"スクレイピング開始: keyword={keyword}, session={session_id}")
        return jsonify({
            "success": True,
            "session_id": session_id,
            "output_dir": str(out_dir),
            "resume": resume,
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
            "min_price": min(i.get("price", 0) for i in group),
            "max_price": max(i.get("price", 0) for i in group),
            "seller_ids": list(set(i.get("seller_id", "") for i in group if i.get("seller_id"))),
        })

    return jsonify({
        "groups": result_groups,
        "total_groups": total_groups,
        "page": page,
        "per_page": per_page,
        "total_pages": (total_groups + per_page - 1) // per_page,
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


# ─────────────────────────────────────────────
# セッション管理
# ─────────────────────────────────────────────

@app.route("/api/sessions")
def api_sessions():
    """過去のセッション一覧"""
    return jsonify({"sessions": _list_sessions()})


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


def _list_sessions():
    """過去セッションの一覧を返す"""
    base = Path(config.OUTPUT_BASE_DIR)
    if not base.exists():
        return []
    sessions = []
    for d in sorted(base.iterdir(), reverse=True):
        if d.is_dir():
            progress_file = d / "progress.json"
            if progress_file.exists():
                try:
                    with open(progress_file) as f:
                        p = json.load(f)
                    sessions.append({
                        "name": d.name,
                        "keyword": p.get("keyword", ""),
                        "status": p.get("status", ""),
                        "total_items": p.get("total_items", 0),
                        "updated_at": p.get("updated_at", ""),
                    })
                except Exception:
                    sessions.append({"name": d.name})
    return sessions[:20]


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
    logger.info("  2. ブラウザで http://localhost:5000 を開く（自動で開きます）")
    logger.info("  3. UIでキーワードを入力して「スクレイピング開始」をクリック")
    logger.info("")


if __name__ == "__main__":
    check_env()

    # ブラウザを自動で開く（少し遅らせる）
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://{config.FLASK_HOST}:{config.FLASK_PORT}")

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
