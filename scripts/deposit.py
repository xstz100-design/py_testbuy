"""BPTrading Deposit Script - Python + Playwright (Chromium)

Flow:
  1. Login via /#/trade (reuse session)
  2. Navigate to /#/finance  (Deposit tab is default)
  3. Payment method "UPI Pay / Bank Card" is auto-selected
  4. Enter amount in the "Enter amount" input
  5. Click "Continue" button
  6. Screenshot the result page and return

Usage:
    python deposit.py --amount 500
    python deposit.py --account 33334444 --password 123456 --amount 500
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
from config import ACCOUNT, PASSWORD, BASE_URL, BROWSER, TIMEOUT, DELAYS

from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(_INSTANCE_DIR).resolve() if _INSTANCE_DIR else ROOT_DIR
_SCREENSHOT_DIR_ENV = os.environ.get("BP_SCREENSHOT_DIR")
if _SCREENSHOT_DIR_ENV:
    SCREENSHOT_DIR = Path(_SCREENSHOT_DIR_ENV)
    AUTH_FILE = SCREENSHOT_DIR / "auth.json"
else:
    SCREENSHOT_DIR = DATA_DIR / "screenshots"
    AUTH_FILE = DATA_DIR / "auth.json"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

FINANCE_URL = f"{BASE_URL}/#/finance"


def output_result(result: dict):
    print(f"\n===RESULT===\n{json.dumps(result)}\n===END===")


def shot(page, name: str) -> str:
    p = str(SCREENSHOT_DIR / f"deposit-{name}.png")
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


def deposit(account: str, password: str, amount: str) -> dict:
    """Execute deposit flow. Returns result dict."""
    print(f"\n{'='*40}")
    print(f"  Desktop Deposit")
    print(f"  Account: {account}")
    print(f"  Amount : $ {amount}")
    print(f"{'='*40}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=BROWSER["headless"],
            slow_mo=BROWSER["slow_mo"],
        )
        ctx_opts = {"viewport": BROWSER["viewport"], "locale": "zh-CN"}
        if AUTH_FILE.exists():
            ctx_opts["storage_state"] = str(AUTH_FILE)
            print("[init] Session restored")

        context = browser.new_context(**ctx_opts)
        context.set_default_timeout(TIMEOUT["element"])
        page = context.new_page()
        page.on("dialog", lambda dlg: dlg.accept())

        try:
            login(page, context, account, password)

            # Navigate to Finance page (Deposit tab is default)
            print("[deposit] Navigating to Finance page...")
            page.goto(FINANCE_URL, wait_until="domcontentloaded", timeout=TIMEOUT["navigation"])
            page.wait_for_timeout(2000)

            # Verify Deposit tab is active (or click it)
            deposit_tab = page.get_by_text("Deposit", exact=True).first
            if deposit_tab.count() > 0:
                deposit_tab.click()
                page.wait_for_timeout(800)
            print("[deposit] On Deposit tab")

            # The payment method (UPI Pay / Bank Card) is auto-selected — no action needed.

            # Fill the "Enter amount" input (right side, NOT the calculator input)
            # Both inputs show the same amount but we target the one in the "Enter amount" panel
            print(f"[deposit] Entering amount: {amount}")
            # Locate the input inside the "Enter amount" section
            amount_input = page.locator("input").filter(has_text="").nth(0)  # fallback

            # Try to find it more precisely: the section heading "Enter amount" > nearby input
            # From DOM observation: there are 2 textboxes on this page; the right one is at index 1
            inputs = page.locator("input[type='text'], input:not([type])")
            n = inputs.count()
            print(f"  [deposit] Found {n} inputs on page")

            # Use the second input (index 1) which is in the "Enter amount" panel
            target_input = inputs.nth(1) if n >= 2 else inputs.first

            target_input.click(force=True)
            page.wait_for_timeout(300)
            # Select all and replace
            target_input.press("Control+A")
            target_input.type(str(amount), delay=50)
            page.wait_for_timeout(500)

            # Verify the value
            current_val = target_input.input_value()
            print(f"  [deposit] Input value: {current_val}")

            shot(page, f"before-confirm-{int(time.time())}")

            # Click "Continue" button
            print("[deposit] Clicking Continue...")
            continue_btn = page.get_by_role("button", name=re.compile(r"continue", re.I))
            if continue_btn.count() == 0:
                raise RuntimeError("Continue button not found on Deposit page")
            continue_btn.first.click()
            page.wait_for_timeout(3000)

            # Screenshot result
            shot_path = shot(page, f"result-{int(time.time())}")

            # Try to read any confirmation text
            page_text = page.locator("body").inner_text()
            # Look for relevant confirmation keywords
            confirmed = any(kw in page_text.lower() for kw in [
                "success", "submitted", "confirm", "payment", "order", "deposit",
                "pending", "processing",
            ])

            print(f"[deposit] Result captured. Page keywords found: {confirmed}")
            return {
                "status": "ok",
                "amount": amount,
                "message": "Deposit request submitted" if confirmed else "Continue clicked — check screenshot",
                "screenshot": shot_path,
            }

        except Exception as e:
            shot(page, f"error-{int(time.time())}")
            print(f"[deposit] Error: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description="BPTrading Deposit Script")
    parser.add_argument("--account", default=ACCOUNT)
    parser.add_argument("--password", default=PASSWORD)
    parser.add_argument("--amount", required=True, help="Deposit amount in USD")
    args = parser.parse_args()

    result = deposit(args.account, args.password, args.amount)
    output_result(result)


if __name__ == "__main__":
    main()
