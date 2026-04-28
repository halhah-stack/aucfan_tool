"""
gemini_client.py - Gemini API による画像・テキスト判定
- 同一商品判定（Vision API）
- 除外カテゴリ判定（食品・衣類・AC100V商品 etc.）
- 安全リスク判定（要確認フラグ）
- 無料枠レート制限: 15RPM → 14RPM で安全運用
"""
import logging
import time
import threading
import yaml
from pathlib import Path
from typing import List, Optional, Tuple

import config

logger = logging.getLogger(__name__)

# Gemini API が使えない場合のフォールバック用
_GEMINI_AVAILABLE = False
genai = None

if config.GEMINI_ENABLED and config.GEMINI_API_KEY:
    try:
        import google.generativeai as genai_module
        genai_module.configure(api_key=config.GEMINI_API_KEY)
        genai = genai_module
        _GEMINI_AVAILABLE = True
        logger.info("Gemini API: 初期化成功")
    except Exception as e:
        logger.warning(f"Gemini API 初期化失敗（pHashのみで動作します）: {e}")
else:
    if not config.GEMINI_ENABLED:
        logger.info("Gemini API: 無効（GEMINI_ENABLED=false）")
    elif not config.GEMINI_API_KEY:
        logger.info("Gemini API: APIキー未設定（pHashのみで動作します）")


# ─────────────────────────────────────────────
# プロンプト読み込み（prompts.yaml から外部ロード）
# ─────────────────────────────────────────────

def _load_prompts() -> dict:
    """prompts.yaml を読み込む。ファイルがなければデフォルト値を返す"""
    yaml_path = Path(__file__).parent / "prompts.yaml"
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        logger.info(f"prompts.yaml を読み込みました: {yaml_path}")
        return data or {}
    except FileNotFoundError:
        logger.warning("prompts.yaml が見つかりません。デフォルトプロンプトを使用します。")
        return {}
    except Exception as e:
        logger.warning(f"prompts.yaml 読み込みエラー: {e}。デフォルトプロンプトを使用します。")
        return {}

_PROMPTS = _load_prompts()

def _get_prompt(key: str) -> str:
    """指定キーのプロンプトを返す（yamlになければデフォルト）"""
    return _PROMPTS.get(key, _DEFAULT_PROMPTS.get(key, ""))

# デフォルトプロンプト（prompts.yaml が壊れた場合のフォールバック）
_DEFAULT_PROMPTS = {
    "exclude_absolute": """
以下の商品が「絶対除外カテゴリ」に該当するか判定してください。

絶対除外カテゴリ:
1. 食品・飲料・サプリメント・口に入る可能性があるもの
2. 衣類・ファッション系（服・靴・バッグ・アクセサリー等）
3. 家庭用コンセント（AC100V）を直接使用する商品（延長コード・家電等）
   ※ただしUSB給電・シガーソケット・乾電池・充電池を使う商品はOK

商品タイトル: {title}

以下のJSON形式で回答してください（説明不要）:
{{
  "excluded": true または false,
  "reason": "除外理由（excluded=trueの場合のみ）",
  "category": "food" または "fashion" または "ac100v" または "none"
}}
""",
    "review_flag": """
以下の商品が「安全リスク要確認カテゴリ」に該当するか判定してください。

要確認カテゴリ（フラグを立てるだけ、除外はしない）:
1. 車・バイクの重要保安部品（ブレーキ・ステアリング・サスペンション等、破損が事故直結）
2. 乗り物の構造部品で破損が怪我に直結するもの

商品タイトル: {title}

以下のJSON形式で回答してください（説明不要）:
{{
  "needs_review": true または false,
  "reason": "要確認理由（needs_review=trueの場合のみ）"
}}
""",
    "brand_check": """
以下の商品タイトルから、「有名ブランド品」かどうか判定してください。

判定基準:
- ノーブランド・ジェネリック・無名メーカー → false（除外しない）
- 有名ブランド（Nike・Apple・Sony・LEGO等）→ true（除外対象）

商品タイトル: {title}

以下のJSON形式で回答してください（説明不要）:
{{
  "is_branded": true または false,
  "brand_name": "ブランド名（is_branded=trueの場合）"
}}
""",
    "size_check": """
以下の商品情報から、「大型サイズ（梱包サイズが45×35×20cmを超える）」かどうか判定してください。

商品タイトル: {title}
サイズ情報: {size_info}

以下のJSON形式で回答してください（説明不要）:
{{
  "is_oversized": true または false,
  "reason": "判定理由"
}}
""",
    "same_product": """
以下の商品画像を見て、「同一商品（個数違い・色違い含む）」かどうか判定してください。

以下のJSON形式で回答してください（説明不要）:
{{
  "same_product": true または false,
  "confidence": "high" または "medium" または "low"
}}
""",
}


class GeminiClient:
    """Gemini API クライアント（レート制限付き）"""

    def __init__(self):
        self.available = _GEMINI_AVAILABLE
        self._lock = threading.Lock()
        self._call_times: List[float] = []  # RPM管理用

        if self.available:
            self._model_vision = genai.GenerativeModel(config.GEMINI_MODEL_VISION)
            self._model_text = genai.GenerativeModel(config.GEMINI_MODEL_TEXT)

    # ─────────────────────────────────────────────
    # レート制限
    # ─────────────────────────────────────────────

    def _wait_for_rate_limit(self):
        """RPM制限を守るために必要なら待機"""
        with self._lock:
            now = time.time()
            # 60秒以内の呼び出し回数を確認
            self._call_times = [t for t in self._call_times if now - t < 60]
            if len(self._call_times) >= config.GEMINI_RPM_LIMIT:
                # 最も古い呼び出しから60秒後まで待機
                wait = 60 - (now - self._call_times[0]) + 0.5
                if wait > 0:
                    logger.info(f"Gemini レート制限: {wait:.1f}秒待機")
                    time.sleep(wait)
            self._call_times.append(time.time())

    def _call_text(self, prompt: str) -> Optional[str]:
        """テキスト生成APIを呼び出す"""
        if not self.available:
            return None
        try:
            self._wait_for_rate_limit()
            resp = self._model_text.generate_content(prompt)
            return resp.text.strip()
        except Exception as e:
            logger.warning(f"Gemini テキストAPI エラー: {e}")
            return None

    def _call_vision(self, prompt: str, image_paths: List[Path]) -> Optional[str]:
        """画像+テキスト生成APIを呼び出す"""
        if not self.available:
            return None
        try:
            self._wait_for_rate_limit()
            from PIL import Image as PILImage
            parts = [prompt]
            for p in image_paths:
                if p and p.exists():
                    img = PILImage.open(p)
                    parts.append(img)
            if len(parts) <= 1:
                return None
            resp = self._model_vision.generate_content(parts)
            return resp.text.strip()
        except Exception as e:
            logger.warning(f"Gemini Vision API エラー: {e}")
            return None

    def _parse_json(self, text: Optional[str]) -> Optional[dict]:
        """JSONレスポンスをパース"""
        if not text:
            return None
        import json
        import re
        # Markdown コードブロックを除去
        text = re.sub(r"```(?:json)?", "", text).strip()
        try:
            return json.loads(text)
        except Exception:
            # 部分的にJSONを探す
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
        logger.debug(f"JSON パース失敗: {text[:200]}")
        return None

    # ─────────────────────────────────────────────
    # 判定メソッド
    # ─────────────────────────────────────────────

    def check_excluded_category(self, title: str) -> Tuple[bool, str]:
        """
        絶対除外カテゴリか判定。
        Returns: (excluded: bool, reason: str)
        """
        if not self.available:
            return False, ""

        prompt = _get_prompt("exclude_absolute").format(title=title)
        result = self._parse_json(self._call_text(prompt))

        if result is None:
            return False, ""

        excluded = bool(result.get("excluded", False))
        reason = result.get("reason", "")
        if excluded:
            logger.info(f"除外判定: {title[:40]} → {reason}")
        return excluded, reason

    def check_needs_review(self, title: str) -> Tuple[bool, str]:
        """
        安全リスク要確認フラグの判定。
        Returns: (needs_review: bool, reason: str)
        """
        if not self.available:
            return False, ""

        prompt = _get_prompt("review_flag").format(title=title)
        result = self._parse_json(self._call_text(prompt))

        if result is None:
            return False, ""

        needs_review = bool(result.get("needs_review", False))
        reason = result.get("reason", "")
        if needs_review:
            logger.info(f"要確認フラグ: {title[:40]} → {reason}")
        return needs_review, reason

    def check_branded(self, title: str) -> Tuple[bool, str]:
        """
        有名ブランド品か判定（ノーブランドのみ仕入れ候補）。
        Returns: (is_branded: bool, brand_name: str)
        """
        if not self.available:
            return False, ""

        prompt = _get_prompt("brand_check").format(title=title)
        result = self._parse_json(self._call_text(prompt))

        if result is None:
            return False, ""

        is_branded = bool(result.get("is_branded", False))
        brand = result.get("brand_name", "")
        return is_branded, brand

    def check_oversized(self, title: str, size_info: str = "") -> Tuple[bool, str]:
        """
        大型サイズ商品か判定。
        Returns: (is_oversized: bool, reason: str)
        """
        if not self.available:
            return False, ""

        prompt = _get_prompt("size_check").format(title=title, size_info=size_info or "不明")
        result = self._parse_json(self._call_text(prompt))

        if result is None:
            return False, ""

        is_oversized = bool(result.get("is_oversized", False))
        reason = result.get("reason", "")
        return is_oversized, reason

    def check_same_product_vision(
        self, image_paths: List[Path]
    ) -> Tuple[bool, str]:
        """
        複数の商品画像が同一商品（個数違い・色違い含む）か判定。
        Returns: (same_product: bool, confidence: str)
        """
        if not self.available or not image_paths:
            return False, "low"

        valid_paths = [p for p in image_paths if p and p.exists()]
        if len(valid_paths) < 2:
            return False, "low"

        result = self._parse_json(self._call_vision(_get_prompt("same_product"), valid_paths))

        if result is None:
            return False, "low"

        same = bool(result.get("same_product", False))
        confidence = result.get("confidence", "low")
        return same, confidence

    def classify_item_full(self, title: str, image_path: Optional[Path] = None) -> dict:
        """
        商品の総合判定を行い、判定結果辞書を返す。
        複数のAPIを呼び分ける（レート制限に配慮）
        """
        result = {
            "excluded": False,
            "exclude_reason": "",
            "needs_review": False,
            "review_reason": "",
            "is_branded": False,
            "brand_name": "",
            "is_oversized": False,
        }

        if not self.available:
            return result

        # 1. 絶対除外カテゴリ
        excluded, reason = self.check_excluded_category(title)
        result["excluded"] = excluded
        result["exclude_reason"] = reason
        if excluded:
            return result  # 除外確定なら以降の判定をスキップ

        # 2. 要確認フラグ
        needs_review, review_reason = self.check_needs_review(title)
        result["needs_review"] = needs_review
        result["review_reason"] = review_reason

        # 3. ブランド判定
        is_branded, brand_name = self.check_branded(title)
        result["is_branded"] = is_branded
        result["brand_name"] = brand_name

        return result
