"""
1688_scraper.py — 1688商品ページ スクレイパー

【使い方】
  from 1688_scraper import fetch_1688_from_url
  data = fetch_1688_from_url("https://detail.1688.com/offer/XXXXXXXX.html")

【戻り値 dict】
  success (bool)
  title (str)             商品名
  shop_name (str)         ショップ名
  shop_url (str)          ショップURL（クエリパラメータ除去済み）
  shop_rating (str)       店舗評価（例: "4.0分"）
  shop_repeat_rate (str)  回頭率（例: "47%"）
  min_price (float)       最低価格（元）
  moq (int)               最小発注数
  moq_unit (str)          単位（套/个/件等）
  variants (list)         [{name, price, stock}] — バリアント一覧
  image_urls (list)       商品画像URLリスト（cbu01.alicdn.com）
  attributes (dict)       商品属性テーブル
  url (str)               スクレイピングした実URL

【前提条件】
  - start.sh で Chrome をポート 9222 デバッグモードで起動済み
  - amazon_scraper.py と同じ Selenium 接続方式
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ── 翻訳ヘルパー ────────────────────────────────────────────────────────
def _translate_zh_to_ja(text: str) -> str:
    """
    中国語テキストを日本語に翻訳する。
    deep_translator (GoogleTranslator) を使用。
    未インストール・通信失敗時は空文字を返す。
    """
    if not text or text == "デフォルト":
        return ""
    try:
        from deep_translator import GoogleTranslator
        result = GoogleTranslator(source="zh-CN", target="ja").translate(text)
        return result or ""
    except ImportError:
        logger.debug("deep_translator 未インストール。pip install deep-translator で追加可能。")
        return ""
    except Exception as e:
        logger.warning(f"翻訳失敗 ({text[:30]}): {e}")
        return ""


# ── Chrome接続 ──────────────────────────────────────────────────────────
def _connect_chrome():
    """既存Chromeのデバッグポートに接続。"""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        import config
        opts = Options()
        opts.debugger_address = f"{config.CHROME_DEBUG_HOST}:{config.CHROME_DEBUG_PORT}"
        driver = webdriver.Chrome(options=opts)
        return driver
    except Exception as e:
        logger.warning(f"Chrome接続失敗: {e}")
        return None


# ── テキストパーサー ────────────────────────────────────────────────────
def _parse_price_from_text(text: str) -> Optional[float]:
    """
    価格コンテナのテキストから主価格（元）を抽出する。

    例:
      "新人价 ¥ 16 .50 20件预估到手单价 ¥ 17 .00 20套起批"  → 17.0
      "新人价 ¥ 12 .50 首件预估到手价 ¥ 13 .50 1个起批"      → 13.5
    """
    # 「预估到手单价」または「预估到手价」の後の価格を優先取得
    # 改行や空白で分割されていることがあるため柔軟にパース
    m = re.search(r'预估到手[单]?价\s*¥\s*(\d+)\s*[.\s]\s*(\d{1,2})\b', text)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")

    # フォールバック: テキスト中の ¥数字 を全て取得して最小値を返す
    prices = re.findall(r'¥\s*(\d+(?:\.\d+)?)', text)
    if prices:
        vals = [float(p) for p in prices if float(p) > 0]
        return min(vals) if vals else None
    return None


def _parse_moq_from_text(text: str) -> tuple[int, str]:
    """
    テキストから MOQ（起批数）と単位を抽出する。
    例: "20套起批" → (20, "套")
        "1个起批"  → (1, "个")
    デフォルト: (1, "个")
    """
    m = re.search(r'(\d+)\s*([套件个片组只盒条双])\s*起批', text)
    if m:
        return int(m.group(1)), m.group(2)
    return 1, "个"


def _parse_variants_from_body(body_text: str) -> list[dict]:
    """
    ページ本文のバリアントセクションから SKU 一覧を抽出する。

    セクションヘッダーとして 规格 / 尺寸 / 颜色 / 型号 / 款式 等に対応。
    ※ 套餐（セット販売）は別商品の組み合わせであり、実バリアントではないため
      エントリポイントから除外し、途中で出現したらパースを終了する。

    フォーマット A（価格・在庫が別行）:
      小方镜
      ¥13.5
      库存199个

    フォーマット B（価格・在庫が同一行）:
      正圆95*95【一对装】
      ¥0.74库存436478套

    バリアントなし（単品）の場合は空リストを返す。
    """
    # 実バリアントのセクションヘッダー（套餐は除外）
    ENTRY_HEADERS  = {'规格', '尺寸', '颜色', '型号', '款式', '规格型号', '包装规格'}
    # これらに出会ったらバリアントセクション終了とみなす
    STOP_HEADERS   = {'套餐', '数量', '颜色分类'}
    ALL_HEADERS    = ENTRY_HEADERS | STOP_HEADERS

    variants = []
    lines = [l.strip() for l in body_text.split('\n') if l.strip()]

    # バリアントセクション開始を探す（ENTRY_HEADERS のみ）
    start = -1
    for i, line in enumerate(lines):
        if line in ENTRY_HEADERS:
            start = i + 1
            break
    if start == -1:
        return []

    i = start
    while i < len(lines):
        name    = lines[i]
        next_ln = lines[i + 1] if i + 1 < len(lines) else ""

        # 別のセクションヘッダーに到達したらパース終了
        if name in ALL_HEADERS:
            break

        # ゴミデータ除外（短すぎる・記号のみ・価格行自体を名前と誤認しない）
        if (len(name) < 2
                or not re.search(r'[\w一-鿿\[\]【】]', name)
                or re.match(r'^¥', name)):
            i += 1
            continue

        # フォーマット B: ¥price库存N が同一行
        combined_m = re.match(r'¥\s*(\d+(?:\.\d+)?)库存(\d+)', next_ln)
        if combined_m:
            variants.append({
                "name":  name,
                "price": float(combined_m.group(1)),
                "stock": int(combined_m.group(2)),
            })
            i += 2
            continue

        # フォーマット A: ¥price と 库存N が別行
        price_m = re.match(r'¥\s*(\d+(?:\.\d+)?)', next_ln)
        if price_m:
            stock_ln = lines[i + 2] if i + 2 < len(lines) else ""
            stock_m  = re.search(r'库存(\d+)', stock_ln)
            variants.append({
                "name":  name,
                "price": float(price_m.group(1)),
                "stock": int(stock_m.group(1)) if stock_m else 0,
            })
            i += 3
            continue

        i += 1

    return variants


def _parse_shop_info(driver) -> dict:
    """
    ショップ名・URL・評価情報を取得する。
    複数の検出戦略を順番に試し、最初に見つかった結果を返す。
    """
    from selenium.webdriver.common.by import By

    info = {"name": "", "url": "", "rating": "", "repeat_rate": "", "years": ""}

    try:
        # body テキストを先に取得（評価情報・年数はここから）
        body = driver.find_element(By.TAG_NAME, "body").text

        # ── ① CSSセレクタでショップリンクを探す ─────────────────────
        # 1688ショップURLパターン:
        #   shop*.1688.com / member.1688.com/shop / supplier.1688.com
        shop_els = driver.find_elements(By.CSS_SELECTOR, "a[href*='.1688.com']")
        for el in shop_els:
            href = el.get_attribute("href") or ""
            text = (el.text or "").strip().split('\n')[0].strip()
            is_shop_url = bool(re.search(
                r'(shop[^/]*\.1688\.com|member\.1688\.com/shop|supplier\.1688\.com)',
                href
            ))
            is_product_url = bool(re.search(
                r'(detail\.|/offer/|/search|/page/offerlist)',
                href
            ))
            if is_shop_url and not is_product_url and text and len(text) >= 2:
                info["url"]  = re.sub(r'\?.*$', '', href)
                info["name"] = text
                break

        # ── ② クラス名ベースのフォールバック ────────────────────────
        if not info["name"]:
            for sel in [
                "[class*='company-name']",
                "[class*='companyName']",
                "[class*='shop-name']",
                "[class*='seller-name']",
                "[class*='supplierName']",
                "[class*='sellerName']",
            ]:
                try:
                    els = driver.find_elements(By.CSS_SELECTOR, sel)
                    for el in els:
                        text = (el.text or "").strip().split('\n')[0].strip()
                        if text and len(text) >= 2 and any('一' <= c <= '鿿' for c in text):
                            info["name"] = text
                            # 親要素からhrefを探す
                            try:
                                parent = el.find_element(By.XPATH, "..")
                                href = parent.get_attribute("href") or ""
                                if ".1688.com" in href:
                                    info["url"] = re.sub(r'\?.*$', '', href)
                            except Exception:
                                pass
                            break
                    if info["name"]:
                        break
                except Exception:
                    pass

        # ── ③ ボディテキストからショップ名を補完 ────────────────────
        # ショップ名が取れなかった場合、「入驻X年」の直前行を試みる
        if not info["name"]:
            lines = [l.strip() for l in body.split('\n') if l.strip()]
            for idx, line in enumerate(lines):
                if re.search(r'入驻\d+年|入驻\d+个月', line):
                    # 直前の行がショップ名候補（中国語2文字以上）
                    for back in range(1, 4):
                        candidate = lines[idx - back] if idx - back >= 0 else ""
                        if (candidate and len(candidate) >= 2
                                and any('一' <= c <= '鿿' for c in candidate)
                                and not re.search(r'[¥$€\d.]+', candidate)):
                            info["name"] = candidate
                            break
                    break

        # ── 評価情報（ボディテキストから） ──────────────────────────
        m = re.search(r'店铺回头率\s*(\d+%)', body)
        if m:
            info["repeat_rate"] = m.group(1)

        m = re.search(r'店铺服务分\s*([\d.]+分)', body)
        if m:
            info["rating"] = m.group(1)

        # 入驻年数
        m = re.search(r'入驻(\d+)年', body)
        if m:
            info["years"] = f"{m.group(1)}年"
        else:
            m = re.search(r'入驻(\d+)个月', body)
            if m:
                info["years"] = f"{m.group(1)}ヶ月"

    except Exception as e:
        logger.warning(f"ショップ情報取得エラー: {e}")

    return info


# ── メイン取得関数 ──────────────────────────────────────────────────────
def fetch_1688_from_url(url: str) -> dict:
    """
    1688 商品ページ URL を指定してデータを取得する。
    既存の Chrome（port 9222）に接続し、新規タブでページを開いてスクレイピングする。
    """
    driver = _connect_chrome()
    if not driver:
        return {"success": False, "error": "Chromeに接続できません（port 9222）"}

    original_handle = None
    new_handle      = None

    try:
        from selenium.webdriver.common.by import By

        # ── localhostタブを起点にする ───────────────────────────────
        # 複数タブが開いている場合、localhostタブを起点に新タブを開くことで
        # 余計な親子関係を避ける。
        original_handle = driver.current_window_handle
        for h in driver.window_handles:
            try:
                driver.switch_to.window(h)
                if "localhost" in driver.current_url:
                    original_handle = h
                    break
            except Exception:
                pass

        # ── 新規タブを開く（差分方式で確実に新タブを特定）──────────
        handles_before = set(driver.window_handles)
        try:
            driver.switch_to.new_window('tab')
        except Exception:
            driver.execute_script("window.open('about:blank');")
        handles_after = set(driver.window_handles)
        new_handles = handles_after - handles_before
        new_handle = new_handles.pop() if new_handles else driver.window_handles[-1]
        driver.switch_to.window(new_handle)
        driver.get(url)

        # ── ページ読み込み待機（最大15秒）──────────────────────────
        for _ in range(30):
            time.sleep(0.5)
            try:
                title_el = driver.find_elements(By.CSS_SELECTOR, ".offer-title")
                if title_el and title_el[0].text.strip():
                    break
            except Exception:
                pass

        # ── 商品タイトル ────────────────────────────────────────────
        # AliPrice等のプラグインが上部に別商品を注入することがあるため、
        # 全候補を収集して「最も文字数が多いもの」をメインタイトルとして採用する。
        title = ""
        title_candidates = []
        for sel in [".offer-title", "[class*='offer-title']", "[class*='title-text']"]:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    t = el.text.strip()
                    if t and any('一' <= c <= '鿿' for c in t):
                        title_candidates.append(t)
            except Exception:
                pass
        if title_candidates:
            # 最長テキストをメインタイトルとして採用
            title = max(title_candidates, key=len)

        # ── ショップ情報 ─────────────────────────────────────────────
        shop = _parse_shop_info(driver)

        # ── 価格 & MOQ ──────────────────────────────────────────────
        min_price: Optional[float] = None
        moq      = 1
        moq_unit = "个"
        try:
            price_els = driver.find_elements(
                By.CSS_SELECTOR, "[class*='od-price-container']"
            )
            if price_els:
                price_text = price_els[0].text
                min_price  = _parse_price_from_text(price_text)
                moq, moq_unit = _parse_moq_from_text(price_text)
        except Exception as e:
            logger.warning(f"価格取得エラー: {e}")

        # ── ページ本文テキスト ────────────────────────────────────────
        body_text = driver.find_element(By.TAG_NAME, "body").text

        # MOQ が取れなかった場合はボディ全体から再検索
        if moq == 1 and moq_unit == "个":
            moq, moq_unit = _parse_moq_from_text(body_text)

        # ── SKU バリアント ───────────────────────────────────────────
        variants = _parse_variants_from_body(body_text)

        if not variants:
            # バリアントなし → 単一バリアントとして返す
            stock = 0
            m_stock = re.search(r'库存(\d+)[套个件片组只]', body_text)
            if m_stock:
                stock = int(m_stock.group(1))
            variants = [{
                "name":    "デフォルト",
                "name_ja": "",
                "price":   min_price or 0.0,
                "stock":   stock,
            }]
        else:
            # バリアントがある場合、最低価格を再計算
            prices = [v["price"] for v in variants if v["price"] > 0]
            if prices:
                min_price = min(prices)
            # 各バリアント名を日本語に翻訳
            for v in variants:
                v["name_ja"] = _translate_zh_to_ja(v.get("name", ""))

        # ── タイトルを日本語に翻訳 ────────────────────────────────────
        title_ja = _translate_zh_to_ja(title)

        # ── 商品属性 ─────────────────────────────────────────────────
        attributes: dict[str, str] = {}
        try:
            attr_els = driver.find_elements(
                By.CSS_SELECTOR, "[class*='module-od-product-attributes']"
            )
            if attr_els:
                attr_text = attr_els[0].text
                attr_lines = [l.strip() for l in attr_text.split('\n') if l.strip()]
                # ヘッダー行「商品属性」をスキップ
                if attr_lines and attr_lines[0] == '商品属性':
                    attr_lines = attr_lines[1:]
                for idx in range(0, len(attr_lines) - 1, 2):
                    key = attr_lines[idx]
                    val = attr_lines[idx + 1]
                    if key and val and key != val:
                        attributes[key] = val
        except Exception as e:
            logger.warning(f"属性取得エラー: {e}")

        # ── 画像URL ──────────────────────────────────────────────────
        image_urls: list[str] = []
        seen: set[str] = set()
        for sel in ["img[src*='cbu01']", "img[src*='ibank']"]:
            try:
                imgs = driver.find_elements(By.CSS_SELECTOR, sel)
                for img in imgs:
                    src = (img.get_attribute("src")
                           or img.get_attribute("data-src") or "")
                    if (src and src not in seen
                            and not src.endswith('.svg')
                            and ('cbu01' in src or 'ibank' in src)):
                        seen.add(src)
                        image_urls.append(src)
            except Exception:
                pass

        actual_url = driver.current_url

        logger.info(
            f"1688スクレイピング完了: {title[:40]} "
            f"/ {len(variants)}バリアント / 画像{len(image_urls)}枚"
        )

        return {
            "success":          True,
            "title":            title,
            "title_ja":         title_ja,
            "shop_name":        shop["name"],
            "shop_url":         shop["url"],
            "shop_rating":      shop["rating"],
            "shop_repeat_rate": shop["repeat_rate"],
            "shop_years":       shop["years"],
            "min_price":        min_price or 0.0,
            "moq":              moq,
            "moq_unit":         moq_unit,
            "variants":         variants,
            "image_urls":       image_urls,
            "attributes":       attributes,
            "url":              actual_url,
        }

    except Exception as e:
        logger.error(f"1688スクレイピングエラー: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

    finally:
        # タブを閉じて localhost タブに戻る（amazon_scraper.py と同じ方式）
        try:
            if new_handle and new_handle in driver.window_handles:
                driver.switch_to.window(new_handle)
                if len(driver.window_handles) > 1:
                    driver.close()
                else:
                    driver.get("http://localhost:5001/research")
        except Exception:
            pass
        try:
            for h in driver.window_handles:
                try:
                    driver.switch_to.window(h)
                    if "localhost" in driver.current_url:
                        break
                except Exception:
                    pass
            # Chrome画面を前面に表示（リサーチ追記ツールをフォーカス）
            try:
                driver.execute_script("window.focus();")
            except Exception:
                pass
        except Exception:
            pass
