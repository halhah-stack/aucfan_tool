"""
services/scraping.py — スクレイピングビジネスロジック

スクレイピングスレッドのターゲット関数を定義する。
Flask・グローバル状態に依存しないため単体テスト可能。

【方針】
  - スクレイピングのルート（api_start/stop/resume/progress）はapp.pyに残す
    （薄いグルー関数のため分離不要）
  - スレッドが実行するビジネスロジックのみここに定義する

2026-05-30 app.py から分離
"""
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


def run_keyword_scraping(
    data_manager,
    image_processor,
    gemini_client,
    stop_event: threading.Event,
    login_check_event: threading.Event,
    resume: bool,
    start_url: str,
    out_dir: Path,
    save_export_files_fn,
):
    """
    STEP1 キーワードスクレイピングのスレッドターゲット関数。

    Args:
        data_manager:         DataManager インスタンス
        image_processor:      ImageProcessor インスタンス
        gemini_client:        GeminiClient インスタンス
        stop_event:           停止シグナル用 threading.Event
        login_check_event:    ログイン確認用 threading.Event
        resume:               前回セッション再開フラグ
        start_url:            開始URL（iPhoneから貼り付けたURL、任意）
        out_dir:              セッション出力フォルダ（Path）
        save_export_files_fn: 完了後に呼ぶエクスポート保存関数
                              (例: services.export._save_export_files)
    """
    from scraper import AucFanScraper

    scraper = AucFanScraper(
        data_manager=data_manager,
        image_processor=image_processor,
        gemini_client=gemini_client,
        stop_event=stop_event,
        login_check_event=login_check_event,
    )
    scraper.run(resume=resume, start_url=start_url or None)

    # STEP1完了後にCSV・HTML・PDFを自動保存
    final_status = data_manager.get_progress().get("status", "done")
    if final_status in ("done", "stopped"):
        save_export_files_fn(data_manager, out_dir)
        logger.info(f"STEP1完了後エクスポート保存: {out_dir.name}")
