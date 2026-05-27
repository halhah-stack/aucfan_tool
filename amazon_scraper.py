"""
amazon_scraper.py — Amazon 商品ページデータ取得モジュール

【役割】
  既存の Chrome（リモートデバッグポート 9222）に接続し、
  現在開いている Amazon 商品ページから以下を取得する。

  - ASIN
  - 商品タイトル
  - 価格
  - 商品画像URL（メイン）
  - 商品説明（箇条書き）
  - 仕様表（技術的な詳細）
  - 評価件数・星の数

【使い方】
  from amazon_scraper import fetch_amazon_product
  result = fetch_amazon_product()
  # result は dict または None（エラー時）

【注意】
  - Amazon 商品ページを Chrome で開いた状態で呼び出すこと
  - ログインは不要（未ログインでも取得可能）
  - FBA手数料・在庫数などはログインが必要なため取得しない
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException

import config

logger = logging.getLogger(__name__)


# ── Chrome接続 ────────────────────────────────────────────────────────
def _connect_chrome() -> Optional[webdriver.Chrome]:
    """既存のChromeに接続してdriverを返す。失敗時はNone。"""
    try:
        options = Options()
        options.add_experimental_option(
            "debuggerAddress",
            f"{config.CHROME_DEBUG_HOST}:{config.CHROME_DEBUG_PORT}"
        )
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
        return driver
    except WebDriverException as e:
        logger.error(f"Chrome接続失敗: {e}")
        return None
    except Exception as e:
        logger.error(f"予期しないエラー: {e}")
        return None


# ── ASIN抽出 ─────────────────────────────────────────────────────────
def _extract_asin(url: str) -> Optional[str]:
    """URLからASINを抽出する。"""
    # /dp/XXXXXXXXXX/ 形式
    m = re.search(r"/dp/([A-Z0-9]{10})", url)
    if m:
        return m.group(1)
    # /gp/product/XXXXXXXXXX 形式
    m = re.search(r"/gp/product/([A-Z0-9]{10})", url)
    if m:
        return m.group(1)
    return None


# ── 価格抽出 ──────────────────────────────────────────────────────────
def _extract_price(soup: BeautifulSoup) -> Optional[str]:
    """Amazon商品ページから価格文字列を抽出する。"""
    selectors = [
        ".a-price .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".apexPriceToPay .a-offscreen",
        "#apex_offerDisplay_desktop .a-price .a-offscreen",
        ".a-price-whole",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            price = el.get_text(strip=True)
            if price:
                return price
    return None


# ── ページ解析共通ロジック ────────────────────────────────────────────
def _expand_and_parse(driver, current_url: str) -> dict:
    """
    Selenium driver が対象ページを開いた状態で呼び出す。
    折りたたまれた「商品情報」「詳細を表示」をクリックで展開してから
    ページをパースし、商品データを dict で返す。
    """
    import time
    from selenium.webdriver.common.by import By

    # ── 折りたたみセクションを展開 ────────────────────────────────
    expand_selectors = [
        # 「詳細を表示」「すべて表示」系ボタン
        "#productDetails_expanderSectionShowAll",
        "#productDetails_db_sections .a-expander-prompt",
        "#productDetails_detailBullets_sections1 .a-expander-prompt",
        ".a-expander-prompt",
        # 商品情報テーブルの「さらに表示」
        "[data-action='a-expander-toggle']",
    ]
    for sel in expand_selectors:
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, sel)
            for btn in btns:
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.3)
        except Exception:
            pass

    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")

    asin = _extract_asin(current_url)

    # ── タイトル ──
    title = ""
    el = soup.select_one("#productTitle")
    if el:
        title = el.get_text(strip=True)

    # ── 価格 ──
    price = _extract_price(soup)

    # ── 画像URL（メイン） ──
    image_url = ""
    img_el = soup.select_one("#landingImage, #imgTagWrapperId img, #main-image")
    if img_el:
        image_url = img_el.get("data-old-hires") or img_el.get("src", "")
        if not image_url and img_el.get("data-a-dynamic-image"):
            parts = img_el.get("data-a-dynamic-image", "{}").split('"')
            if len(parts) > 1:
                image_url = parts[1]

    # ── 全画像URL（サブ画像含む） ──
    image_urls = []

    # メイン画像: data-a-dynamic-image に複数URLが入っている
    # 形式: {"url1": [w, h], "url2": [w, h], ...}  → 最大解像度のURLを取る
    def _best_from_dynamic(el) -> Optional[str]:
        raw = el.get("data-a-dynamic-image", "")
        if not raw:
            return None
        try:
            import json
            mapping = json.loads(raw)  # {"url": [w, h], ...}
            if not mapping:
                return None
            # 解像度（w*h）が最大のURLを返す
            best = max(mapping.items(), key=lambda kv: kv[1][0] * kv[1][1])
            return best[0]
        except Exception:
            return None

    # メイン画像
    main_hires = None
    if img_el:
        main_hires = (
            img_el.get("data-old-hires")
            or _best_from_dynamic(img_el)
            or img_el.get("src", "")
        )
        if main_hires:
            image_urls.append(main_hires)
        if not image_url:
            image_url = main_hires or ""

    # サブ画像（サムネイルリスト）
    # セレクターを複数試す
    thumb_selectors = [
        "#altImages li.item img",
        "#imageBlock_thumbnails li img",
        "#thumbs-image img",
        "#altImages ul li img",
        ".imageThumbnail img",
    ]
    seen_urls = set(image_urls)
    for sel in thumb_selectors:
        for thumb_img in soup.select(sel):
            # サムネイルURLを高解像度に変換
            # 例: ...._SS40_.jpg → ...._SL1000_.jpg
            raw_url = (
                thumb_img.get("data-old-hires")
                or _best_from_dynamic(thumb_img)
                or thumb_img.get("src", "")
            )
            if not raw_url or raw_url in seen_urls:
                continue
            # サムネイル解像度 (_SS40_, _AC_US40_ 等) を高解像度に変換
            hi_url = re.sub(r"\._[A-Z]{1,3}\d+_\.", "._SL1000_.", raw_url)
            hi_url = re.sub(r"\._[A-Z]{2}\d+,[A-Z]{2}\d+_\.", "._SL1000_.", hi_url)
            if hi_url not in seen_urls:
                image_urls.append(hi_url)
                seen_urls.add(hi_url)

    # Selenium の JavaScript で altImages の data-a-dynamic-image を取る
    # （BS4 では script タグに入っていることもある）
    try:
        js_data = driver.execute_script("""
            var imgs = [];
            var items = document.querySelectorAll('#altImages li.item');
            items.forEach(function(li) {
                var img = li.querySelector('img');
                if (img) {
                    var dyn = img.getAttribute('data-a-dynamic-image');
                    if (dyn) { imgs.push(dyn); }
                }
            });
            return imgs;
        """)
        if js_data:
            import json
            for raw in js_data:
                try:
                    mapping = json.loads(raw)
                    if mapping:
                        best = max(mapping.items(), key=lambda kv: kv[1][0] * kv[1][1])
                        url = best[0]
                        if url not in seen_urls:
                            image_urls.append(url)
                            seen_urls.add(url)
                except Exception:
                    pass
    except Exception:
        pass

    # ── 箇条書き ──
    bullets = []
    for bel in soup.select("#feature-bullets ul li span.a-list-item"):
        text = bel.get_text(strip=True)
        if text and len(text) > 3:
            bullets.append(text)

    # ── 商品説明 ──
    description = ""
    desc_el = soup.select_one(
        "#productDescription p, "
        "#productDescription_feature_div p, "
        "#bookDescription_feature_div"
    )
    if desc_el:
        description = desc_el.get_text(separator="\n", strip=True)

    # ── 商品情報テーブル（仕様・スペック） ────────────────────────
    # 複数のパターンを順番に試し、全部マージする
    specs = {}

    # パターン1: 商品概要テーブル（ページ上部・折りたたみなし）
    # 例: 取り付けタイプ / フィットタイプ / 自動部品位置 など
    for row in soup.select(
        "#productOverview_feature_div tr, "
        "#glProductDescription_feature_div tr"
    ):
        tds = row.select("td, th")
        if len(tds) >= 2:
            k = tds[0].get_text(strip=True)
            v = tds[1].get_text(strip=True)
            if k and v:
                specs[k] = v

    # パターン2: 技術仕様テーブル（折りたたみ展開後）
    for row in soup.select(
        "#productDetails_techSpec_section_1 tr, "
        "#productDetails_techSpec_section_2 tr, "
        "#productDetails_db_sections tr, "
        "#prodDetails .prodDetTable tr, "
        "#detailBulletsWrapper_feature_div tr"
    ):
        th = row.select_one("th")
        td = row.select_one("td")
        if th and td:
            k = th.get_text(strip=True)
            v = td.get_text(strip=True)
            if k and v and k not in specs:
                specs[k] = v

    # パターン3: dl/dt/dd 形式（新デザイン）
    for li in soup.select("#detailBullets_feature_div ul li"):
        parts = [p.strip() for p in li.get_text(separator="\n", strip=True).split("\n")
                 if p.strip() and p.strip() != ":"]
        if len(parts) >= 2 and parts[0] not in specs:
            specs[parts[0]] = parts[1]

    # パターン4: key-value ペア形式（一部カテゴリ）
    for row in soup.select(
        "#technicalSpecifications_section_1 tr, "
        ".a-section .a-spacing-small table tr"
    ):
        tds = row.select("td")
        if len(tds) >= 2:
            k = tds[0].get_text(strip=True)
            v = tds[1].get_text(strip=True)
            if k and v and k not in specs:
                specs[k] = v

    # ── 評価・レビュー ──
    # 「5つ星のうち4.1」のように表示されるので「のうち」の後の数字を取る
    rating = ""
    rating_selectors = [
        "span[data-hook='rating-out-of-text']",
        "#acrPopover .a-icon-alt",
        ".a-icon-star .a-icon-alt",
        "[data-hook='average-star-rating'] .a-icon-alt",
        "#averageCustomerReviews .a-icon-alt",
    ]
    for sel in rating_selectors:
        rel = soup.select_one(sel)
        if rel:
            text = rel.get_text(strip=True)
            # 「5つ星のうち4.1」→ "のうち" の後を優先
            m = re.search(r"のうち\s*(\d+\.?\d*)", text)
            if not m:
                # "4.1 out of 5" 形式（英語ページ対応）
                m = re.search(r"(\d+\.?\d*)\s*out of", text)
            if not m:
                # フォールバック: 小数点付きの数字
                m = re.search(r"(\d+\.\d+)", text)
            if m:
                rating = m.group(1)
                break

    review_count = ""
    rcel = soup.select_one(
        "#acrCustomerReviewText, "
        "span[data-hook='total-review-count']"
    )
    if rcel:
        review_count = rcel.get_text(strip=True)

    # ── A+コンテンツ検出 ──
    has_aplus = bool(soup.select_one("#aplus, #aplus3PModule, .aplus-v2"))

    return {
        "success":      True,
        "url":          current_url,
        "asin":         asin or "",
        "title":        title,
        "price":        price or "",
        "image_url":    image_url,
        "image_urls":   image_urls,   # 全画像URL（メイン含む）
        "bullets":      bullets,
        "description":  description,
        "specs":        specs,
        "rating":       rating,
        "review_count": review_count,
        "has_aplus":    has_aplus,
    }


# ── メイン取得関数 ────────────────────────────────────────────────────
def fetch_amazon_product() -> dict:
    """
    現在Chromeで開いているAmazon商品ページのデータを取得して返す。

    Returns:
        {
            "success": True/False,
            "error":   エラーメッセージ（失敗時）,
            "url":     ページURL,
            "asin":    ASIN,
            "title":   商品タイトル,
            "price":   価格文字列,
            "image_url": メイン画像URL,
            "bullets": ["特徴1", "特徴2", ...],
            "description": "商品説明テキスト",
            "specs":   {"項目名": "値", ...},
            "rating":  "4.3",
            "review_count": "1,234",
        }
    """
    driver = _connect_chrome()
    if not driver:
        return {"success": False, "error": "Chromeに接続できません。start.sh でアプリを起動してください。"}

    try:
        # Amazon商品タブを探す
        amazon_handle = None
        current_url = ""
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            url = driver.current_url
            if "amazon.co.jp" in url and ("/dp/" in url or "/gp/product/" in url):
                amazon_handle = handle
                current_url = url
                break

        if not amazon_handle:
            # Amazon商品ページ以外が開いている場合は現在のタブURLを確認
            current_url = driver.current_url
            if "amazon.co.jp" not in current_url:
                return {
                    "success": False,
                    "error": "Chromeで amazon.co.jp の商品ページを開いてから実行してください。"
                }
            # amazon.co.jpは開いているが /dp/ がない（カテゴリページなど）
            return {
                "success": False,
                "error": "商品ページ（/dp/...）を開いてください。カテゴリページや検索結果ページは対象外です。"
            }

        result = _expand_and_parse(driver, current_url)
        logger.info(f"Amazon取得完了: {result.get('asin')} / {result.get('title','')[:40]}")
        return result

    except Exception as e:
        logger.error(f"Amazon取得エラー: {e}", exc_info=True)
        return {"success": False, "error": f"取得中にエラーが発生しました: {e}"}

    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ── URL指定取得 ───────────────────────────────────────────────────────
def resolve_short_url(url: str) -> str:
    """
    短縮URL（amzn.asia など）をリダイレクト先の実URLに解決する。
    解決できない場合は元のURLをそのまま返す。
    """
    import urllib.request
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            final = resp.url
            logger.info(f"短縮URL解決: {url} → {final}")
            return final
    except Exception as e:
        logger.warning(f"短縮URL解決失敗（元URLを使用）: {e}")
        return url


def fetch_amazon_from_url(url: str) -> dict:
    """
    URLを指定してAmazon商品ページのデータを取得する。
    短縮URL（amzn.asia/d/... など）にも対応。
    Chromeの新規タブで開いてスクレイピングし、タブを閉じて戻る。

    Args:
        url: Amazon商品ページURL（短縮URL可）

    Returns:
        fetch_amazon_product() と同形式の dict
    """
    import time

    # 短縮URL解決
    resolved_url = resolve_short_url(url)

    driver = _connect_chrome()
    if not driver:
        return {"success": False, "error": "Chromeに接続できません（port 9222）"}

    original_handle = None
    new_handle = None

    try:
        # ── アプリタブ（リサーチツール）を特定する ───────────────────
        # localhost / 127.0.0.1 / :5001 のいずれかにマッチするタブを探す
        def _is_app_tab(url: str) -> bool:
            return any(x in url for x in ("localhost", "127.0.0.1", ":5001"))

        app_handle = None
        for h in driver.window_handles:
            try:
                driver.switch_to.window(h)
                if _is_app_tab(driver.current_url):
                    app_handle = h
                    break
            except Exception:
                pass
        # 見つからなければ先頭を退避先として使う
        original_handle = app_handle or driver.window_handles[0]

        # ── AucFanが開いたAmazon検索タブをCDPで閉じる ──────────────
        # Seleniumの window_handles は現在フォーカス中のChromeウィンドウの
        # タブしか見えないことがある。別ウィンドウのタブを確実に操作するために
        # CDP（Chrome DevTools Protocol）の Target API を使う。
        #
        # 閉じる対象: amazon.co.jp かつ /dp/ を含まない（検索・一覧ページ）
        # 残す対象  : /dp/ を含む商品ページ（ユーザーが選択したタブ）
        closed_amazon = 0
        try:
            result  = driver.execute_cdp_cmd("Target.getTargets", {})
            targets = result.get("targetInfos", [])
            for t in targets:
                url       = t.get("url", "")
                target_id = t.get("targetId", "")
                is_amazon       = "amazon.co.jp" in url
                is_product_page = "/dp/" in url or "/gp/product/" in url
                if is_amazon and not is_product_page and target_id:
                    try:
                        driver.execute_cdp_cmd(
                            "Target.closeTarget", {"targetId": target_id}
                        )
                        closed_amazon += 1
                        logger.info(f"Amazon検索タブを閉じました: {url[:70]}")
                    except Exception as e:
                        logger.warning(f"CDPタブクローズ失敗: {e}")
        except Exception as e:
            logger.warning(f"CDP Target.getTargets 失敗: {e}")
        if closed_amazon:
            logger.info(f"合計 {closed_amazon} 個のAmazon検索タブを閉じました")

        # アプリタブに戻る
        try:
            driver.switch_to.window(original_handle)
        except Exception:
            if driver.window_handles:
                driver.switch_to.window(driver.window_handles[0])
                original_handle = driver.window_handles[0]

        # 新規タブを開いてURLへ移動
        # 開く前後のハンドル差分で確実に新タブを特定する。
        handles_before = set(driver.window_handles)
        try:
            driver.switch_to.new_window('tab')
        except Exception:
            driver.execute_script("window.open('about:blank');")
        handles_after = set(driver.window_handles)
        new_handles = handles_after - handles_before
        new_handle = new_handles.pop() if new_handles else driver.window_handles[-1]
        driver.switch_to.window(new_handle)
        driver.get(resolved_url)

        # ページ読み込み待機（最大10秒）
        for _ in range(20):
            time.sleep(0.5)
            cur = driver.current_url
            if "amazon.co.jp" in cur and ("/dp/" in cur or "/gp/product/" in cur):
                break
            if "amazon.co.jp" in cur and "/dp/" not in cur and "/gp/product/" not in cur:
                # Amazonには到達したが商品ページではない（トップや検索ページ等）
                break

        current_url = driver.current_url

        # Amazon商品ページか確認
        if "amazon.co.jp" not in current_url:
            return {
                "success": False,
                "error": f"Amazon.co.jp のページではありません（リダイレクト先: {current_url[:80]}）"
            }
        if "/dp/" not in current_url and "/gp/product/" not in current_url:
            return {
                "success": False,
                "error": "商品ページ（/dp/...）に到達できませんでした。URLを確認してください。"
            }

        result = _expand_and_parse(driver, current_url)
        result["input_url"] = url   # 元の入力URL（短縮URLそのまま）を付加
        logger.info(f"Amazon URL取得完了: {result.get('asin')} / {result.get('title','')[:40]}")
        return result

    except Exception as e:
        logger.error(f"Amazon URL取得エラー: {e}", exc_info=True)
        return {"success": False, "error": f"取得中にエラー: {e}"}

    finally:
        # 開いたタブを閉じて /research タブに戻る
        try:
            if new_handle and new_handle in driver.window_handles:
                driver.switch_to.window(new_handle)
                remaining = driver.window_handles
                if len(remaining) > 1:
                    # 他のタブ/ウィンドウがある → このタブだけ閉じる
                    driver.close()
                else:
                    # このタブが唯一の場合は閉じずに localhost へ移動
                    # （closeするとChromeウィンドウごと閉じてしまうため）
                    try:
                        driver.get("http://localhost:5001/research")
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            # アプリタブ（リサーチツール）を探して前面に戻す
            research_handle = None
            for h in driver.window_handles:
                try:
                    driver.switch_to.window(h)
                    cur = driver.current_url
                    if any(x in cur for x in ("localhost", "127.0.0.1", ":5001")):
                        research_handle = h
                        break
                except Exception:
                    pass
            if not research_handle:
                if original_handle and original_handle in driver.window_handles:
                    driver.switch_to.window(original_handle)
            # Chrome画面を前面に表示（リサーチ追記ツールをフォーカス）
            try:
                driver.execute_script("window.focus();")
            except Exception:
                pass
        except Exception:
            pass
        # quit()は呼ばない（Chromeを閉じないため）
