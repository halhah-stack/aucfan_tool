"""
services/session.py — セッション管理ビジネスロジック

セッション一覧取得・フォルダ名パース等の純粋関数。
app.py のルートハンドラから切り出した関数群。
Flask・グローバル状態に依存しないため単体テスト可能。

2026-05-30 app.py から分離
"""
import os
import re
import json
import logging
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

def parse_session_info(name: str) -> dict:
    """フォルダ名から表示用情報を解析する（新旧両命名規則対応）。"""
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



def list_sessions(base_dir: Path, running_names: set, step: int = None):
    """過去セッションの一覧を返す。step を指定するとそのステップのみ返す。"""
    base = base_dir
    if not base.exists():
        return []


    # 有効なセッション名パターン（新形式: S1_20260506_01_キーワード / 旧形式: keyword_20260506_123456）
    _SESS_PAT = re.compile(r'^S[123]_\d{8}_\d+|^.+_\d{8}_\d{6}$')

    sessions = []
    try:
        entries = sorted(base.iterdir(), reverse=True)
    except Exception as e:
        logger.warning(f"セッション一覧の読み込みに失敗しました（Google Drive同期中の可能性）: {e}")
        return []

    for d in entries:
        try:
            if not d.is_dir():
                continue
        except Exception:
            continue

        info = parse_session_info(d.name)
        if step is not None and info["step"] != step:
            continue

        progress_file = d / "progress.json"
        is_valid_session_name = bool(_SESS_PAT.match(d.name))

        if not is_valid_session_name:
            # 命名規則外のフォルダはデータファイルがある場合のみ表示
            try:
                has_data = (progress_file.exists() or
                            (d / "results.csv").exists() or
                            (d / "items.json").exists())
            except Exception:
                has_data = False
            if not has_data:
                continue

        p = {}
        try:
            if progress_file.exists():
                with open(progress_file, encoding="utf-8") as f:
                    p = json.load(f)
        except Exception:
            pass  # Google Drive 同期中で読み込めない場合はスキップせず空データで続行

        # 完全に空（ファイルなし）なフォルダは削除残骸とみなしてスキップ
        if is_valid_session_name and not p:
            try:
                has_any_file = any(True for _ in d.iterdir())
            except Exception:
                has_any_file = True  # 確認できない場合は表示する
            if not has_any_file:
                continue

        sessions.append({
            "name": d.name,
            "step": info["step"],
            "session_type": info["session_type"],   # 後方互換
            "label": info["label"],
            "date_str": info["date_str"],
            "num": info["num"],
            "keyword": p.get("keyword", info["label"]),
            "source_keyword": p.get("source_keyword", ""),   # 元STEP1キーワード
            "machine_name": p.get("machine_name", ""),       # 実行したMac名
            "status": p.get("status", "unknown"),
            "total_items": p.get("total_items", 0),
            "started_at": p.get("started_at", ""),
            "updated_at": p.get("updated_at", ""),
            "has_csv": (d / "results.csv").exists(),
            "is_running": d.name in running_names,
        })

    return sessions[:100]

