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
以下の商品タイトルが「絶対除外カテゴリ」に該当するか判定してください。

絶対除外カテゴリ:
1. 【食品・食材・飲料・農産物・水産物・畜産物・加工食品・調味料】
   ▼ これらは品目を問わず「すべて excluded」とする包括ルール ▼
   - 水産物・貝類：サザエ・アワビ・ホタテ・ハマグリ・カキ・ウニ・イクラ・エビ・カニ・マグロ・
     サーモン・鮭・サバ・タコ・イカ・烏賊・干物・塩辛・水産加工品 等
   - 農産物：野菜・果物（メロン・スイカ・桃・梨・りんご・いちご・ぶどう 等）・きのこ・松茸
   - 畜産物・肉類：牛肉・豚肉・鶏肉・ラム肉・馬肉・ジビエ 等
   - 加工食品・お菓子：缶詰・レトルト・冷凍食品・お菓子・スイーツ・珍味・インスタント食品 等
   - 調味料・粉類：醤油・みそ・ソース・ドレッシング・砂糖・塩・小麦粉・料理酒 等
   - 飲料全般：ビール・ワイン・日本酒・焼酎・ウイスキー・ジュース・お茶・コーヒー豆 等
   - その他：サプリメント・口に入る可能性があるものすべて
   ※ 個別の品目判断より「食品・食材・飲料・食べ物・飲み物」という包括ルールを優先すること
   ※ 食品と調理器具・鍋等がセットになっている商品（食材セット・鍋セット・詰め合わせ・
     お取り寄せ・グルメセット・食べ比べ等）も excluded。調理器具単体はこのルールの対象外。
2. 衣類・ファッション系（服・靴・バッグ・アクセサリー等）
   （例：フライトジャケット・ムートン・コート・本革・防寒服・ラムレザー・羊皮製品等も含む）
3. 家庭用コンセント（AC100V）を直接使用する商品（延長コード・家電等）
   ※ただしUSB給電・シガーソケット・乾電池・充電池を使う商品はOK
4. 危険物・高圧ガス
   （エアコンガス・冷媒ガス・フロン・HFCガス・R134a・R410A・R32・ガス缶・スプレー缶・
     ガスボンベ・高圧ガス・危険物 等）
5. トレーディングカード本体
   （ポケモンカード・遊戯王・MTG・デュエマ・ワンピースカード・ドラゴンボールカード等の
     シングルカード・パック・ボックス・デッキ本体）
   ▼ 以下はOK（除外しない）▼
   カードケース・スリーブ・カードバインダー・デッキケース・カード収納グッズ・プレイマット
   （タイトルにカード名・弾名・レアリティが含まれる → カード本体として excluded）
   （タイトルに「ケース」「スリーブ」「バインダー」「収納」「プレイマット」→ ok）

商品タイトル: {title}

以下のJSON形式で回答してください（説明不要）:
{{
  "excluded": true または false,
  "reason": "除外理由（excluded=trueの場合のみ）",
  "category": "food" または "fashion" または "ac100v" または "hazmat" または "trading_card" または "none"
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
以下の商品タイトルから、「有名ブランド品・有名メーカー品」かどうか判定してください。

除外対象（is_branded=true）:
- 有名ブランドの公式品・純正品（Nike・Apple・Sony・LEGO・任天堂等）
- 有名家電メーカー（HITACHI・Panasonic・SHARP・Toshiba・三菱・富士通等）の製品
- 有名カメラメーカー（Canon・Nikon・Fujifilm等）の製品
- タイトル先頭にメーカー名が来ている場合（例：「HITACHI 冷蔵庫...」「Panasonic テレビ...」）

除外しない（is_branded=false）:
- ノーブランド・ジェネリック・無名メーカー
- ブランドのロゴや製品が写り込んでいるだけのサードパーティ製品
  （例：「Switch対応 非純正カバー」）
- 【重要】自動車・バイク・カー用品カテゴリの商品
  タイトルに車種名（ハイエース・プリウス・アルファード・ジムニー・N-BOX等）や
  カー用品（カーナビ・ドライブレコーダー・ETC・タイヤ・ホイール等）、
  バイク関連（バイク・スクーター・ヘルメット・グローブ等）のワードが含まれる場合は、
  トヨタ・ホンダ・ヤマハ・スズキ等の自動車メーカー名があっても is_branded=false にする
  （例: 「Toyota ハイエース用 シートカバー」「ホンダ フィット カーマット」→ false）

商品タイトル: {title}

以下のJSON形式で回答してください（説明不要）:
{{
  "is_branded": true または false,
  "brand_name": "ブランド・メーカー名（is_branded=trueの場合）"
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
    "vision_classify": """
以下の商品画像とタイトルを見て、販売可否を判定してください。

商品タイトル: {title}

【result = "excluded" にする条件】以下のいずれかに該当:
1. 【食品・飲料・食材】▼ 包括ルール（最優先）▼
   「画像またはタイトルに食品・飲料・食材と認識できるものが1つでも含まれれば必ず excluded」
   個別品目の判断より、この包括ルールを最優先すること。迷ったら excluded にする。
   ▼対象カテゴリ（例示であり、これ以外の食品・飲料・食材も全て対象）▼
   ・水産物・貝類全般：サザエ・アワビ・ホタテ・カキ・ウニ・イクラ・エビ・カニ・マグロ・
     サーモン・鮭・タコ・イカ・干物・塩辛・水産加工品 等
   ・農産物：野菜・果物（メロン・スイカ・桃・梨・りんご・いちご・ぶどう）・きのこ・松茸 等
   ・畜産物・肉類：牛肉・豚肉・鶏肉・ラム肉・卵・乳製品 等
   ・加工食品：お菓子・珍味・レトルト・缶詰・冷凍食品・インスタント食品 等
   ・飲料全般：ビール・ワイン・日本酒・焼酎・ウイスキー・ジュース・お茶・コーヒー 等
   ・調味料：醤油・みそ・ソース・ドレッシング・砂糖・塩 等
   ・サプリメント・その他口に入る可能性があるもの全て
   ※ 商品本体が食品でなくても、包装・袋・パッケージ・ラベルに食品が描かれていれば除外する
   ※ タイトルに食品・食材・飲料を示す単語があれば画像確認なしで excluded にする
   ※ 鍋・調理器具の中に食材が入っている、または食品と一緒に並べられている画像は excluded。
     調理器具単体（空の鍋・フライパン等のみが写っている）は ok。
2. 衣類・ファッション系（服・靴・バッグ・アクセサリー等）
   （例：フライトジャケット・ムートン・コート・本革製品・防寒服・ラムレザー・羊皮製品等も含む）
3. 家庭用コンセント（AC100V）を直接使用する商品（延長コード・家電等）
   ※ただしUSB給電・シガーソケット・乾電池・充電池を使う商品はOK
4. 危険物・高圧ガス
   （エアコンガス・冷媒ガス・フロン・HFCガス・R134a・R410A・R32・ガス缶・スプレー缶・
     ガスボンベ・高圧ガス・危険物 等。ラベルや缶に該当表記が写っていても除外する）
5. トレーディングカード本体
   ・画像にポケモンカード・遊戯王・MTG・デュエマ等のイラスト入りトレーディングカードが
     主な商品として写っている場合は excluded
   ・ただしカードを収納・保護するケース・スリーブ・バインダー・プレイマットが
     主な商品であれば ok（除外しない）
6. 有名ブランドの公式品・純正品（Nike・Apple・Sony・LEGO・任天堂純正等）
   ▼ブランド判定の重要ルール▼
   ・「商品そのもの」がブランド公式品かどうかで判断する
   ・ブランドのロゴや製品が「写り込んでいるだけ」のサードパーティ製品は除外しない
   ・例（除外しない）: Switch対応サードパーティ製カバー・保護フィルム
   ・例（除外する）: Apple純正ケーブル、LEGO公式セット
   ▼自動車・バイク・カー用品は特別ルール▼
   ・タイトルや画像が車種専用品（ハイエース・プリウス等の車種名付き）や
     カー用品（カーナビ・ETC・タイヤ・ホイール等）、バイク関連（ヘルメット・グローブ等）
     の場合は、Toyota・Honda・Yamaha等のメーカー名が含まれていても除外しない
   ・例（除外しない）: 「Toyota ハイエース用 シートカバー」「Honda フィット カーマット」

【result = "review" にする条件】除外はしないが要確認:
- 車・バイクの重要保安部品（ブレーキ・ステアリング・サスペンション等、破損が事故直結）
- 乗り物の構造部品で破損が怪我に直結するもの

【result = "ok"】上記いずれにも該当しない場合

以下のJSON形式で回答してください（説明不要）:
{{
  "result": "excluded" または "review" または "ok",
  "reason": "判定理由（okの場合は空文字でよい）",
  "brand_name": "ブランド名（ブランド品除外の場合のみ、それ以外は空文字）"
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
        image_path が指定された場合は Vision API で1回の呼び出しで判定（レート節約）。
        image_path がない場合はテキストAPIを3回呼び分ける。
        """
        result = {
            "excluded": False,
            "exclude_reason": "",
            "needs_review": False,
            "review_reason": "",
            "is_branded": False,
            "brand_name": "",
            "is_oversized": False,
            "gemini_source": "",   # "vision" or "text"
            "gemini_reason": "",   # 主な判定理由（UI表示用）
        }

        if not self.available:
            return result

        # ── Vision API による一括判定（画像あり） ──
        if image_path is not None and Path(image_path).exists():
            prompt = _get_prompt("vision_classify").format(title=title)
            raw = self._call_vision(prompt, [Path(image_path)])
            parsed = self._parse_json(raw)
            if parsed is not None:
                vision_result = parsed.get("result", "ok")  # "excluded" / "review" / "ok"
                reason = parsed.get("reason", "")
                brand_name = parsed.get("brand_name", "")

                result["gemini_source"] = "vision"
                result["gemini_reason"] = reason

                if vision_result == "excluded":
                    result["excluded"] = True
                    if brand_name:
                        result["is_branded"] = True
                        result["brand_name"] = brand_name
                        result["exclude_reason"] = f"ブランド品: {brand_name}"
                    else:
                        result["exclude_reason"] = reason
                    logger.info(f"Vision除外判定: {title[:40]} → {result['exclude_reason']}")
                elif vision_result == "review":
                    result["needs_review"] = True
                    result["review_reason"] = reason
                    logger.info(f"Vision要確認フラグ: {title[:40]} → {reason}")

                return result
            else:
                logger.warning(f"Vision判定パース失敗、テキスト判定にフォールバック: {title[:40]}")

        # ── テキストAPIによる逐次判定（画像なし or Vision失敗時） ──
        result["gemini_source"] = "text"

        # 1. 絶対除外カテゴリ
        excluded, reason = self.check_excluded_category(title)
        result["excluded"] = excluded
        result["exclude_reason"] = reason
        if excluded:
            result["gemini_reason"] = reason
            return result  # 除外確定なら以降の判定をスキップ

        # 2. 要確認フラグ
        needs_review, review_reason = self.check_needs_review(title)
        result["needs_review"] = needs_review
        result["review_reason"] = review_reason
        if needs_review:
            result["gemini_reason"] = review_reason

        # 3. ブランド判定
        is_branded, brand_name = self.check_branded(title)
        result["is_branded"] = is_branded
        result["brand_name"] = brand_name
        if is_branded:
            result["gemini_reason"] = f"ブランド品: {brand_name}"

        return result
