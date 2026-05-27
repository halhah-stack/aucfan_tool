"""
check_1688_detail.py — 1688ページの詳細セレクター確認
"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import re

opts = Options()
opts.debugger_address = "127.0.0.1:9222"
driver = webdriver.Chrome(options=opts)

for h in driver.window_handles:
    driver.switch_to.window(h)
    if "1688.com" in driver.current_url:
        break

print("=== 商品タイトル ===")
for sel in ["[class*='title-text']", "[class*='product-name']",
            "[class*='subject']", "[class*='offer-title']", "h1"]:
    try:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els:
            t = el.text.strip()
            if len(t) > 10 and any('一' <= c <= '鿿' for c in t):
                cls = el.get_attribute("class") or ""
                print(f"  [{sel}] class='{cls[:60]}' → {t[:80]}")
                break
    except: pass

print("\n=== 価格セクション（詳細） ===")
for sel in ["[class*='price-container']", "[class*='price-wrapper']",
            "[class*='price-box']", "[class*='priceText']",
            "[class*='price-int']", "[class*='price-decimal']"]:
    try:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els[:2]:
            t = el.text.strip()
            if t:
                cls = el.get_attribute("class") or ""
                print(f"  [{sel}] class='{cls[:60]}' → {t[:60]}")
    except: pass

print("\n=== MOQ（起批数） ===")
for sel in ["[class*='moq']", "[class*='batch']", "[class*='min-order']",
            "[class*='unit']", "[class*='quote']"]:
    try:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els[:2]:
            t = el.text.strip()
            if t:
                cls = el.get_attribute("class") or ""
                print(f"  [{sel}] class='{cls[:60]}' → {t[:60]}")
    except: pass

# テキストから 起批 を含む行を探す
body = driver.find_element(By.TAG_NAME, "body").text
for line in body.split('\n'):
    if '起批' in line or 'MOQ' in line.upper():
        print(f"  テキスト行: {line.strip()[:80]}")

print("\n=== SKUバリアント ===")
for sel in ["[class*='sku']", "[class*='spec']", "[class*='variant']",
            "[class*='attr']", "[class*='规格']"]:
    try:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els[:3]:
            t = el.text.strip()
            if t and len(t) > 5:
                cls = el.get_attribute("class") or ""
                print(f"  [{sel}] class='{cls[:60]}'\n    → {t[:150]}")
    except: pass

print("\n=== ショップ情報 ===")
for sel in ["[class*='shop-name']", "[class*='store-name']",
            "[class*='seller']", "a[href*='shop']"]:
    try:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els[:2]:
            t = el.text.strip()
            href = el.get_attribute("href") or ""
            if t:
                print(f"  [{sel}] {t[:60]} | href={href[:80]}")
    except: pass

print("\n=== 画像（全枚数） ===")
seen = set()
for sel in ["[class*='detail'] img", "[class*='pic'] img",
            "[class*='image'] img", "img[src*='cbu01']", "img[src*='alicdn']"]:
    try:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els[:5]:
            src = el.get_attribute("src") or el.get_attribute("data-src") or ""
            if src and src not in seen and 'alicdn' in src:
                seen.add(src)
                print(f"  {src[:100]}")
    except: pass

print(f"\n合計画像数（alicdn）: {len(seen)}枚")
print("\n完了")
