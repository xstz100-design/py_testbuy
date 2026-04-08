"""Diagnose withdraw page structure on bptradinguk.com"""
import json, sys, re, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
AUTH = ROOT / "auth.json"
SHOTS = ROOT / "screenshots"
sys.path.insert(0, str(ROOT))
import config

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx_opts = {"viewport": {"width": 1440, "height": 900}, "locale": "zh-CN"}
    if AUTH.exists():
        ctx_opts["storage_state"] = str(AUTH)
    ctx = browser.new_context(**ctx_opts)
    ctx.set_default_timeout(15000)
    page = ctx.new_page()

    # 1. Go to trade page and login
    page.goto(config.TRADE_URL, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(2000)
    pwd_inputs = page.locator('input[type="password"]')
    if pwd_inputs.count() > 0:
        inputs = page.locator("input")
        inputs.nth(0).fill(config.ACCOUNT)
        inputs.nth(1).fill(config.PASSWORD)
        page.locator("button").filter(
            has_text=re.compile(r"log\s*in|login|sign", re.I)
        ).first.click()
        page.wait_for_timeout(3000)
        ctx.storage_state(path=str(AUTH))

    # 2. Get all links/nav items on the main page
    print("=== Current URL:", page.url)
    page.screenshot(path=str(SHOTS / "diag-main.png"))

    # Find all <a> links
    links = page.locator("a[href]")
    count = links.count()
    print(f"=== Found {count} links:")
    for i in range(min(count, 30)):
        href = links.nth(i).get_attribute("href")
        txt = links.nth(i).inner_text()[:50].strip()
        print(f"  [{i}] href={href}  text={txt}")

    # Find nav items or sidebar items
    print("\n=== Nav/sidebar items:")
    for sel in [".nav-item", ".menu-item", ".sidebar-item",
                "[class*=nav]", "[class*=menu]", "[class*=tab]"]:
        items = page.locator(sel)
        c = items.count()
        if c > 0:
            print(f"  {sel}: {c} items")
            for j in range(min(c, 10)):
                txt = items.nth(j).inner_text()[:60].strip().replace("\n", " ")
                print(f"    [{j}] {txt}")

    # Try common withdraw URLs
    print("\n=== Exploring /#/finance page:")
    page.goto(config.BASE_URL + "/#/finance", wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(3000)
    page.screenshot(path=str(SHOTS / "diag-finance.png"))
    
    # Get full body text
    body = page.locator("body").inner_text()
    print("=== Full body text:")
    print(body[:2000])
    
    # Find all buttons
    print("\n=== Buttons:")
    btns = page.locator("button")
    for i in range(min(btns.count(), 20)):
        txt = btns.nth(i).inner_text()[:60].strip()
        print(f"  [{i}] {txt}")
    
    # Find text with withdraw/withdrawal
    print("\n=== Text containing withdraw/withdrawal/cash:")
    all_text = body
    for keyword in ["withdraw", "cash", "transfer", "send", "payout", "Withdraw", "提现"]:
        if keyword.lower() in all_text.lower():
            idx = all_text.lower().index(keyword.lower())
            context = all_text[max(0,idx-50):idx+100]
            print(f"  Found '{keyword}' at pos {idx}: ...{context}...")
    
    # Find tabs / clickable items
    print("\n=== Divs/spans with text:")
    for sel in ["div.tab", "[class*=tab]", "[class*=withdraw]", "[class*=cash]", 
                ".menu-item", "[role=tab]", "[class*=btn]", "[class*=button]"]:
        items = page.locator(sel)
        c = items.count()
        if c > 0:
            print(f"  {sel}: {c} items")
            for j in range(min(c, 10)):
                txt = items.nth(j).inner_text()[:80].strip().replace("\n", " ")
                if txt:
                    print(f"    [{j}] {txt}")
    
    # Find all inputs
    print("\n=== Inputs:")
    inputs = page.locator("input:visible")
    for i in range(min(inputs.count(), 10)):
        ph = inputs.nth(i).get_attribute("placeholder") or ""
        tp = inputs.nth(i).get_attribute("type") or ""
        print(f"  [{i}] type={tp} placeholder={ph}")
    
    # Check if there are sub-pages in finance
    print("\n=== Links inside finance:")
    links_in = page.locator("a[href]")
    for i in range(links_in.count()):
        href = links_in.nth(i).get_attribute("href")
        txt = links_in.nth(i).inner_text()[:50].strip()
        if txt:
            print(f"  [{i}] href={href}  text={txt}")

    # Try clicking on text that might be withdraw
    print("\n=== Clicking 'Withdrawal' tab:")
    try:
        loc = page.get_by_text("Withdrawal", exact=True)
        if loc.count() > 0:
            loc.first.click()
            page.wait_for_timeout(3000)
            
            # Click USDT Account
            print("\n=== Clicking 'USDT Account':")
            usdt = page.get_by_text("USDT Account", exact=True)
            if usdt.count() > 0:
                usdt.first.click()
                page.wait_for_timeout(2000)
                page.screenshot(path=str(SHOTS / "diag-usdt-selected.png"))
                
                body = page.locator("body").inner_text()
                print("Body after USDT click:")
                print(body[:2000])
                
                # Find all inputs
                print("\n=== ALL Inputs:")
                inputs = page.locator("input")
                for i in range(min(inputs.count(), 20)):
                    ph = inputs.nth(i).get_attribute("placeholder") or ""
                    tp = inputs.nth(i).get_attribute("type") or ""
                    val = inputs.nth(i).input_value() or ""
                    vis = inputs.nth(i).is_visible()
                    cls = inputs.nth(i).get_attribute("class") or ""
                    print(f"  [{i}] type={tp} placeholder='{ph}' value='{val}' visible={vis} class='{cls[:50]}'")
                
                # Find all buttons
                print("\n=== ALL Buttons:")
                btns = page.locator("button")
                for i in range(min(btns.count(), 15)):
                    txt = btns.nth(i).inner_text()[:60].strip()
                    vis = btns.nth(i).is_visible()
                    cls = btns.nth(i).get_attribute("class") or ""
                    print(f"  [{i}] text='{txt}' visible={vis} class='{cls[:50]}'")
                
                # Find submit/confirm/continue type elements
                print("\n=== div/span with submit/confirm/continue/withdrawal text:")
                for kw in ["Submit", "Confirm", "Continue", "Withdraw", "Request", "Apply", "Send"]:
                    els = page.get_by_text(kw, exact=False)
                    c = els.count()
                    if c > 0:
                        print(f"  '{kw}': {c} elements")
                        for j in range(min(c, 5)):
                            tag = els.nth(j).evaluate("el => el.tagName")
                            txt = els.nth(j).inner_text()[:60].strip()
                            cls = els.nth(j).evaluate("el => el.className")
                            vis = els.nth(j).is_visible()
                            print(f"    [{j}] <{tag}> text='{txt}' class='{str(cls)[:60]}' vis={vis}")
                
                # Get HTML of the withdrawal view
                print("\n=== WithdrawalView HTML:")
                wd_view = page.locator(".WithdrawalView")
                if wd_view.count() > 0:
                    html = wd_view.inner_html()
                    print(html[:3000])
            else:
                print("  USDT Account not found")
            
            # Also try Bank Account
            print("\n=== Clicking 'Bank Account':")
            bank = page.get_by_text("Bank Account", exact=True)
            if bank.count() > 0:
                bank.first.click()
                page.wait_for_timeout(2000)
                page.screenshot(path=str(SHOTS / "diag-bank-selected.png"))
                
                body = page.locator("body").inner_text()
                print("Body after Bank click:")
                print(body[:1500])
                
                # Inputs
                print("\n=== Inputs after Bank:")
                inputs = page.locator("input:visible")
                for i in range(min(inputs.count(), 15)):
                    ph = inputs.nth(i).get_attribute("placeholder") or ""
                    tp = inputs.nth(i).get_attribute("type") or ""
                    val = inputs.nth(i).input_value() or ""
                    print(f"  [{i}] type={tp} ph='{ph}' value='{val}'")
    except Exception as e:
        import traceback
        print(f"  Error: {e}")
        traceback.print_exc()

    ctx.close()
    browser.close()
    print("\nDone")
