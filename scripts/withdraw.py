"""BPTrading Withdrawal Script - Python + Playwright (Chromium)

Flow:
  1. Login via /#/trade (reuse session)
  2. Navigate to /#/finance
  3. Click "Withdrawal" tab
  4. Fill amount in input.ant-input
  5. Select "USDT Account" or "Bank Account"
  6. For USDT: fill ERC20 address in textarea
  7. Click "confirm" button
  8. Check result and screenshot

Usage:
    python withdraw.py --account 33334444 --password 123456 --amount 100 --erc20 TMzz...m1 --method usdt
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Multi-instance support
_INSTANCE_DIR = os.environ.get("BP_INSTANCE_DIR")
if _INSTANCE_DIR:
    sys.path.insert(0, str(Path(_INSTANCE_DIR).resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import BASE_URL, BROWSER, TIMEOUT, DELAYS

from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(_INSTANCE_DIR).resolve() if _INSTANCE_DIR else ROOT_DIR
AUTH_FILE = DATA_DIR / "auth.json"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)


def output_result(result: dict):
    print(f"\n===RESULT===\n{json.dumps(result)}\n===END===")


def shot(page, name: str) -> str:
    p = str(SCREENSHOT_DIR / f"withdraw-{name}.png")
    page.screenshot(path=p)
    print(f"  [screenshot] {p}")
    return p


def login(page, context, account: str, password: str):
    """Navigate to site and login if needed."""
    trade_url = f"{BASE_URL}/#/trade"
    for attempt in range(3):
        try:
            page.goto(trade_url, wait_until="domcontentloaded", timeout=TIMEOUT["navigation"])
            break
        except Exception as e:
            if attempt < 2:
                print(f"[login] Attempt {attempt + 1} failed: {e}, retrying...")
                page.wait_for_timeout(3000)
            else:
                raise

    page.wait_for_timeout(DELAYS["page_load"])

    if page.locator('input[type="password"]').count() > 0:
        print("[login] Logging in...")
        inputs = page.locator("input")
        inputs.nth(0).fill(account)
        inputs.nth(1).fill(password)
        page.locator("button").filter(
            has_text=re.compile(r"log\s*in|login|sign", re.I)
        ).first.click()
        page.wait_for_timeout(2000)
        context.storage_state(path=str(AUTH_FILE))
        print("[login] Done")
    else:
        print("[login] Session valid")


def navigate_to_withdrawal(page):
    """Navigate to /#/finance and click Withdrawal tab."""
    finance_url = f"{BASE_URL}/#/finance"
    page.goto(finance_url, wait_until="domcontentloaded", timeout=TIMEOUT["navigation"])
    page.wait_for_timeout(2000)
    print("[withdraw] Navigated to Finance page")

    # Click "Withdrawal" tab
    wd_tab = page.get_by_text("Withdrawal", exact=True)
    if wd_tab.count() == 0:
        raise RuntimeError("Withdrawal tab not found on Finance page")
    wd_tab.first.click()
    page.wait_for_timeout(2000)
    print("[withdraw] Clicked Withdrawal tab")


def fill_amount(page, amount: str):
    """Fill the amount input field."""
    amount_input = page.locator("input.ant-input")
    if amount_input.count() == 0:
        raise RuntimeError("Amount input not found")
    amount_input.first.click(click_count=3)  # Select all
    amount_input.first.fill(amount)
    page.wait_for_timeout(500)
    print(f"[withdraw] Amount set to: {amount}")


def select_usdt_and_fill(page, erc20: str):
    """Select USDT Account and fill ERC20 address."""
    # Click "USDT Account" option
    usdt_option = page.get_by_text("USDT Account", exact=True)
    if usdt_option.count() == 0:
        raise RuntimeError("USDT Account option not found")
    usdt_option.first.click()
    page.wait_for_timeout(1500)
    print("[withdraw] Selected USDT Account")

    # Check the ERC20 checkbox if not already checked
    checkbox = page.locator("input.ant-checkbox-input")
    if checkbox.count() > 0:
        is_checked = checkbox.first.is_checked()
        if not is_checked:
            checkbox.first.click()
            page.wait_for_timeout(500)
            print("[withdraw] Checked ERC20 checkbox")

    # Fill ERC20 address in the textarea or input that appears
    # The field placeholder is "Transfer to ERC20 Address"
    erc20_field = page.locator('textarea, input[type="text"]').filter(
        has_text=""
    )
    # Try textarea first
    textarea = page.locator("textarea")
    if textarea.count() > 0 and textarea.first.is_visible():
        textarea.first.fill(erc20)
        print(f"[withdraw] ERC20 address filled in textarea: {erc20[:15]}...")
    else:
        # Try input fields - find the one after USDT Account section
        # The ERC20 input is the second visible text input (first is amount)
        inputs = page.locator('input[type="text"]:visible')
        if inputs.count() >= 2:
            inputs.nth(1).fill(erc20)
            print(f"[withdraw] ERC20 address filled in input: {erc20[:15]}...")
        else:
            raise RuntimeError("ERC20 address field not found")

    page.wait_for_timeout(500)


def select_bank_and_fill(page, bank_info: dict):
    """Select Bank Account and fill bank details."""
    # Click "Bank Account" option
    bank_option = page.get_by_text("Bank Account", exact=True)
    if bank_option.count() == 0:
        raise RuntimeError("Bank Account option not found")
    bank_option.first.click()
    page.wait_for_timeout(1500)
    print("[withdraw] Selected Bank Account")

    # Bank form has 5 fields: Bank Name, Account Name, Account No., Type, IFSC code
    # They are inputs after the amount input
    inputs = page.locator('input[type="text"]:visible')
    count = inputs.count()
    if count < 6:  # 1 amount + 5 bank fields
        print(f"[withdraw] Warning: expected 6 inputs, found {count}")

    fields = ["bank_name", "account_name", "account_no", "type", "ifsc_code"]
    for i, field in enumerate(fields):
        idx = i + 1  # Skip amount input at index 0
        if idx < count:
            val = bank_info.get(field, "")
            if val:
                inputs.nth(idx).fill(val)
                print(f"[withdraw] Filled {field}: {val}")

    page.wait_for_timeout(500)


def click_confirm(page) -> dict:
    """Click confirm button and check result."""
    # Find the confirm button
    confirm_btn = page.locator("button").filter(
        has_text=re.compile(r"confirm", re.I)
    )
    if confirm_btn.count() == 0:
        shot(page, "no-confirm-btn")
        return {"status": "error", "message": "Confirm button not found"}

    confirm_btn.first.click()
    print("[withdraw] Clicked confirm button")
    page.wait_for_timeout(3000)

    # Take screenshot of result
    shot(page, "result")

    # Check for popups or messages
    body_text = page.locator("body").inner_text()

    # Check for success indicators
    success_keywords = ["success", "submitted", "completed", "pending", "processing",
                        "request has been", "approved"]
    for kw in success_keywords:
        if kw.lower() in body_text.lower():
            return {"status": "ok", "message": "Withdrawal submitted successfully"}

    # Check for error indicators
    error_keywords = ["failed", "error", "insufficient", "invalid", "minimum",
                      "not available", "cannot", "rejected", "denied"]
    for kw in error_keywords:
        if kw.lower() in body_text.lower():
            idx = body_text.lower().index(kw.lower())
            context = body_text[max(0, idx-20):idx+100].strip()
            return {"status": "error", "message": context[:200]}

    # Check for any modal/popup
    modal = page.locator(".ant-modal, .ant-message, [class*=modal], [class*=popup], [class*=toast]")
    if modal.count() > 0:
        modal_text = modal.first.inner_text()[:200].strip()
        if modal_text:
            return {"status": "ok", "message": f"Withdrawal response: {modal_text}"}

    return {"status": "ok", "message": "Withdrawal confirm clicked (check status in Trading history)"}


def run(account: str, password: str, amount: str, erc20: str, method: str):
    print(f"\n{'='*40}")
    print(f"  BPTrading Withdrawal")
    print(f"  Account : {account}")
    print(f"  Amount  : {amount}")
    print(f"  Method  : {method}")
    if method == "usdt":
        print(f"  Address : {erc20[:10]}...{erc20[-6:] if len(erc20) > 10 else erc20}")
    print(f"{'='*40}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=BROWSER["headless"],
            slow_mo=BROWSER["slow_mo"],
        )
        ctx_opts = {"viewport": BROWSER["viewport"], "locale": "zh-CN"}
        if AUTH_FILE.exists():
            ctx_opts["storage_state"] = str(AUTH_FILE)

        context = browser.new_context(**ctx_opts)
        context.set_default_timeout(TIMEOUT["element"])
        page = context.new_page()
        page.on("dialog", lambda dlg: dlg.accept())

        try:
            login(page, context, account, password)
            navigate_to_withdrawal(page)
            fill_amount(page, amount)

            if method == "usdt":
                select_usdt_and_fill(page, erc20)
            else:
                # Bank method - for now just select, user would need to pre-configure bank info
                select_bank_and_fill(page, {})

            shot(page, "before-confirm")
            result = click_confirm(page)
            output_result(result)
        except Exception as e:
            shot(page, "exception")
            result = {"status": "error", "message": str(e)}
            output_result(result)
        finally:
            context.close()
            browser.close()


def main():
    parser = argparse.ArgumentParser(description="BPTrading Withdrawal")
    parser.add_argument("--account", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--amount", required=True)
    parser.add_argument("--erc20", default="")
    parser.add_argument("--method", default="usdt", choices=["usdt", "bank"])
    args = parser.parse_args()

    run(args.account, args.password, args.amount, args.erc20, args.method)


if __name__ == "__main__":
    main()
