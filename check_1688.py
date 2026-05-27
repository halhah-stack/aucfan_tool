"""
check_1688.py — 1688ページのHTML構造を確認するスクリプト
使い方:
  1. Chromeで1688ページを開いておく
  2. ターミナルで: cd ~/Downloads/aucfan_tool && source .venv/bin/activate && python check_1688.py
"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

opts = Options()
opts.debugger_address = "127.0.0.1:9222"
driver = webdriver.Chrome(options=opts)

# 1688タブを探す
found = False
for h in driver.window_handles:
    driver.switch_to.window(h)
    if "1688.com" in driver.current_url:
        found = True
        break

if not found:
    print("❌ 1688タブが見つかりません。Chromeで1688ページを開いてください。")
    exit()

print(f"✅ URL: {driver.current_url}")
print(f"タイトル: {driver.title}")
print("=" * 60)

# ページテキスト全体
body_text = driver.find_element(By.TAG_NAME, "body").text
print("[ページテキスト（先頭3000文字）]")
print(body_text[:3000])
print("=" * 60)

# 商品名候補を探す
print("[商品名候補]")
for sel in ["h1", ".title", ".product-title", "[class*='title']", "[class*='subject']"]:
    try:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els[:3]:
            t = el.text.strip()
            if t:
                print(f"  {sel}: {t[:100]}")
    except:
        pass

# 価格候補
print("\n[価格候補]")
for sel in ["[class*='price']", ".price", ".offer-price", "[class*='amount']"]:
    try:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els[:3]:
            t = el.text.strip()
            if t:
                print(f"  {sel}: {t[:80]}")
    except:
        pass

# 画像URL
print("\n[メイン画像URL候補]")
for sel in ["[class*='main-image'] img", "[class*='detail-img'] img",
            ".module-detail-main-pic img", "img[src*='cbu01']"]:
    try:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        for el in els[:2]:
            src = el.get_attribute("src") or el.get_attribute("data-src") or ""
            if src:
                print(f"  {src[:100]}")
    except:
        pass

print("\n完了")
