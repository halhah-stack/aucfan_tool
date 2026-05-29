"""
services/state.py — アプリケーション状態クラス定義

グローバル変数をクラスに封じ込める。
辞書互換インターフェース（__getitem__/__setitem__）により
既存の _seller_state["key"] 記法を壊さずに段階移行できる。

移行計画:
  Phase 1（完了）: SellerState, MasterState クラス化
  Phase 2（完了）: ScraperState クラス化
  将来: _seller_state["key"] → _seller.key 形式に順次移行

2026-05-30 app.py から分離
"""
import threading
import logging
from typing import Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 辞書互換ベースクラス
# ─────────────────────────────────────────────

class _DictCompatState:
    """
    辞書互換インターフェースを提供する基底クラス。
    _seller_state["running"] のような既存コードをそのまま動作させる。
    """
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)


# ─────────────────────────────────────────────
# STEP2: セラーリサーチ状態
# ─────────────────────────────────────────────

class SellerState(_DictCompatState):
    """
    STEP2 セラーリサーチのグローバル状態。
    旧: _seller_state (dict) + _seller_lock (Lock)
    新: _seller (SellerState) — .lock で Lock にアクセス
    """
    def __init__(self):
        self.sellers: list = []         # [{"seller_id": str, "seller_url": str, "status": ...}]
        self.current_index: int = -1    # 現在処理中のセラーインデックス（-1 = 未開始）
        self.running: bool = False      # SellerAnalyzer スレッドが実行中かどうか
        self.phase: str = "idle"        # "idle"|"scraping_list"|"grouping"|"vision_check"|"done"|"stopped"|"error"
        self.stop_event: Optional[threading.Event] = None   # 停止リクエスト用
        self.thread: Optional[threading.Thread] = None      # SellerAnalyzer スレッド
        self.dm = None                  # 実行中の DataManager
        self.session_id: Optional[str] = None       # 完了セッション ID
        self.output_dir: Optional[Path] = None      # 完了セッション出力ディレクトリ
        self.source_keyword: str = ""   # 元になった STEP1 キーワード名
        self.lock = threading.Lock()    # スレッドセーフ保護（旧: _seller_lock）


# ─────────────────────────────────────────────
# STEP3: マスターセラーリサーチ状態
# ─────────────────────────────────────────────

class MasterState(_DictCompatState):
    """
    STEP3 マスターセラーリサーチのグローバル状態。
    旧: _master_state (dict) + _master_lock (Lock)
    新: _master (MasterState) — .lock で Lock にアクセス
    """
    def __init__(self):
        self.running: bool = False
        self.phase: str = "idle"        # "idle"|"scraping_list"|"grouping"|"vision_check"|"done"|"stopped"|"error"
        self.stop_event: Optional[threading.Event] = None
        self.thread: Optional[threading.Thread] = None
        self.dm = None                  # 実行中の DataManager
        self.session_id: Optional[str] = None
        self.output_dir: Optional[Path] = None
        self.total: int = 0
        self.done: int = 0
        self.current_seller: str = ""
        self.lock = threading.Lock()    # スレッドセーフ保護（旧: _master_lock）


# ─────────────────────────────────────────────
# STEP1: キーワードスクレイピング状態
# ─────────────────────────────────────────────

class ScraperState(_DictCompatState):
    """
    STEP1 キーワードスクレイピングのグローバル状態。
    旧: 複数のグローバル変数（_data_manager, _scraper_thread 等）+ _lock
    新: _s1 (ScraperState) — .lock で Lock にアクセス
    """
    def __init__(self):
        self.thread: Optional[threading.Thread] = None      # スクレイパースレッド
        self.stop_event = threading.Event()                 # set() で停止通知
        self.login_check_event = threading.Event()          # ログイン即時確認トリガー
        self.dm = None                                      # DataManager
        self.image_processor = None                         # ImageProcessor
        self.gemini_client = None                           # GeminiClient
        self.output_dir: Optional[Path] = None             # 現セッションの出力ディレクトリ
        self.lock = threading.Lock()                        # スレッドセーフ保護（旧: _lock）
