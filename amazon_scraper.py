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

        # ASIN
        asin = _extract_asin(current_url)

        # ページHTML取得
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")

        # ── タイトル ──────────────────────────────────────────────────
        title = ""
        title_el = soup.select_one("#productTitle")
        if title_el:
            title = title_el.get_text(strip=True)

        # ── 価格 ──────────────────────────────────────────────────────
        price = _extract_price(soup)

        # ── メイン画像URL ─────────────────────────────────────────────
        image_url = ""
        img_el = soup.select_one("#landingImage, #imgTagWrapperId img, #main-image")
        if img_el:
            image_url = (
                img_el.get("data-old-hires")
                or img_el.get("data-a-dynamic-image", "{}").split('"')[1] if img_el.get("data-a-dynamic-image") else ""
                or img_el.get("src", "")
            )

        # ── 箇条書き（商品の特徴） ────────────────────────────────────
        bullets = []
        bullet_els = soup.select("#feature-bullets ul li span.a-list-item")
        for el in bullet_els:
            text = el.get_text(strip=True)
            if text and len(text) > 3:
                bullets.append(text)

        # ── 商品説明 ──────────────────────────────────────────────────
        description = ""
        desc_el = soup.select_one(
            "#productDescription p, "
            "#productDescription_feature_div p, "
            "#bookDescription_feature_div"
        )
        if desc_el:
            description = desc_el.get_text(separator="\n", strip=True)

        # ── 仕様表（技術的な詳細） ────────────────────────────────────
        specs = {}
        # パターン1: テーブル形式
        for row in soup.select(
            "#productDetails_techSpec_section_1 tr, "
            "#productDetails_techSpec_section_2 tr, "
            "#prodDetails .prodDetTable tr"
        ):
            th = row.select_one("th")
            td = row.select_one("td")
            if th and td:
                key = th.get_text(strip=True)
                val = td.get_text(strip=True)
                if key and val:
                    specs[key] = val

        # パターン2: dl/dt/dd 形式（新デザイン）
        if not specs:
            for dl in soup.select("#detailBullets_feature_div ul li"):
                parts = dl.get_text(separator="\n", strip=True).split("\n")
                parts = [p.strip() for p in parts if p.strip() and p.strip() != ":"]
                if len(parts) >= 2:
                    specs[parts[0]] = parts[1]

        # ── 評価・レビュー件数 ────────────────────────────────────────
        rating = ""
        rating_el = soup.select_one(
            "span[data-hook='rating-out-of-text'], "
            "#acrPopover .a-icon-alt, "
            ".a-icon-star .a-icon-alt"
        )
        if rating_el:
            text = rating_el.get_text(strip=True)
            m = re.search(r"(\d+\.?\d*)", text)
            if m:
                rating = m.group(1)

        review_count = ""
        review_el = soup.select_one(
            "#acrCustomerReviewText, "
            "span[data-hook='total-review-count']"
        )
        if review_el:
            review_count = review_el.get_text(strip=True)

        # ── ライバル件数（検索結果ページとは別・同カテゴリの出品数） ──
        # 「この商品を含む X 件の結果」= 同カテゴリ競合数の参考値
        rival_count = ""
        rival_el = soup.select_one(
            "span[cel_widget_id='MAIN-TOP_RESULTS_COUNT-0'] span, "
            ".a-section .a-spacing-small span"
        )
        # ライバル件数はAmazon検索結果ページで取るのが正確なので、ここでは取得しない

        result = {
            "success":      True,
            "url":          current_url,
            "asin":         asin or "",
            "title":        title,
            "price":        price or "",
            "image_url":    image_url,
            "bullets":      bullets,
            "description":  description,
            "specs":        specs,
            "rating":       rating,
            "review_count": review_count,
        }

        logger.info(f"Amazon取得完了: {asin} / {title[:40]}")
        return result

    except Exception as e:
        logger.error(f"Amazon取得エラー: {e}", exc_info=True)
        return {"success": False, "error": f"取得中にエラーが発生しました: {e}"}

    finally:
        try:
            driver.quit()
        except Exception:
            pass
