"""BPTrading Desktop Trade - Python + Playwright (Chromium)

State-Machine Flow:
  1. ensure_idle()  — 确认无活跃交易 / 关闭残留弹窗
  2. select_currency() + verify  — 选币种 → 验证下拉框显示一致
  3. enter_amount() + verify     — 设金额 → 验证 input 值一致
  4. select_duration() + verify  — 选时长 → 验证高亮
  5. click_direction() + verify  — 下单   → 验证进入 ACTIVE 状态
  6. wait_for_result()           — 等结算 → 截图 → 关闭弹窗 → 回到 IDLE
"""
import sys
import os
import re
import time
import gc
import asyncio
import argparse
import json
import platform
from pathlib import Path

_SELECT_ALL = "Meta+A" if platform.system() == "Darwin" else "Control+A"

# Multi-instance support
_INSTANCE_DIR = os.environ.get("BP_INSTANCE_DIR")
if _INSTANCE_DIR:
    sys.path.insert(0, str(Path(_INSTANCE_DIR).resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    TRADE_URL, ACCOUNT, PASSWORD, BROWSER, TIMEOUT, DELAYS,
    TRADE_DEFAULTS, get_display, get_category,
)
from playwright.sync_api import sync_playwright

ROOT_DIR   = Path(__file__).resolve().parent.parent
DATA_DIR   = Path(_INSTANCE_DIR).resolve() if _INSTANCE_DIR else ROOT_DIR
_SCREENSHOT_DIR_ENV = os.environ.get("BP_SCREENSHOT_DIR")
if _SCREENSHOT_DIR_ENV:
    SCREENSHOT_DIR = Path(_SCREENSHOT_DIR_ENV)
    AUTH_FILE = SCREENSHOT_DIR / "auth.json"
else:
    SCREENSHOT_DIR = DATA_DIR / "screenshots"
    AUTH_FILE = DATA_DIR / "auth.json"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def shot(page, name: str) -> str:
    p = str(SCREENSHOT_DIR / f"trade-{name}.png")
    page.screenshot(path=p)
    print(f"  [screenshot] {p}")
    return p


# ═══════════════════════════════════════
#  Loading 遮罩层处理
# ═══════════════════════════════════════
def wait_for_loading_gone(page, timeout_ms: int = 5000):
    """等待 loading 遮罩层消失，超时后强制移除"""
    try:
        page.wait_for_function(
            """() => {
                const selectors = ['.loading', '.loading-mask', '.ant-spin',
                    '[class*="loading"]', '[class*="spinner"]', '.overlay'];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        if (r.width > 0 && r.height > 0
                            && s.display !== 'none'
                            && s.visibility !== 'hidden'
                            && s.opacity !== '0') {
                            return false;
                        }
                    }
                }
                return true;
            }""",
            timeout=timeout_ms,
        )
    except Exception:
        _safe_eval(page, """() => {
            const selectors = ['.loading', '.loading-mask', '.ant-spin',
                '[class*="loading"]', '[class*="spinner"]', '.overlay'];
            for (const sel of selectors) {
                document.querySelectorAll(sel).forEach(el => {
                    el.style.display = 'none';
                    el.style.visibility = 'hidden';
                    el.style.pointerEvents = 'none';
                });
            }
        }""")
        page.wait_for_timeout(200)


# ═══════════════════════════════════════
#  状态检测
# ═══════════════════════════════════════
def _safe_eval(page, js, arg=None, default=None):
    """page.evaluate() wrapper — returns `default` on navigation/context errors."""
    try:
        return page.evaluate(js, arg) if arg is not None else page.evaluate(js)
    except Exception:
        return default


def get_page_state(page) -> str:
    """返回页面当前状态: idle / active / result / login"""
    # Quick login-page check first (avoid mis-reading ant-select on login)
    try:
        if page.locator('input[type="password"]').count() > 0:
            return "login"
    except Exception:
        pass
    has_result = _safe_eval(page, """() => {
        for (const el of document.querySelectorAll('*')) {
            if (el.textContent.trim() === 'Trade result') {
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                if (r.width > 0 && r.height > 0
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity) > 0) {
                    return true;
                }
            }
        }
        return false;
    }""", default=False)
    if has_result:
        return "result"
    try:
        if page.locator("text=Expiration time").count() > 0:
            return "active"
        if page.locator("text=Estimate profit").count() > 0:
            return "active"
    except Exception:
        pass
    return "idle"


def ensure_idle(page, timeout_s: int = 120):
    """确保页面处于 IDLE 状态才允许后续操作。超时 2 分钟。
    如有活跃交易则等待结算；如有结果弹窗则关闭。"""
    state = get_page_state(page)
    if state == "idle":
        return

    if state == "result":
        print("  [state] Closing leftover result popup...")
        _close_result_popup(page)
        page.wait_for_timeout(1000)
        return

    # state == "active": 正在倒计时，必须等结算
    print(f"  [state] Active trade detected — waiting for settlement (max {timeout_s}s)...")
    start = time.time()
    while time.time() - start < timeout_s:
        st = get_page_state(page)
        if st == "result":
            _close_result_popup(page)
            page.wait_for_timeout(700)
            print("  [state] Previous trade settled, now idle")
            return
        if st == "idle":
            return
        page.wait_for_timeout(1000)
    raise RuntimeError("ensure_idle timeout: account still in active trade")


def _close_result_popup(page):
    # 方法1: JS click close 按钮
    _safe_eval(page, """() => {
        const el = document.querySelector('.stx-ico-close');
        if (el) { el.click(); return; }
        const d = document.querySelector('[class*="TradeResultDialog"]');
        if (d) { const b = d.querySelector('[class*="close"]'); if (b) b.click(); }
    }""")
    page.wait_for_timeout(700)
    # 方法2: 如果弹窗还在，点击空白区域或 X
    try:
        if page.get_by_text("Trade result").count() > 0:
            _safe_eval(page, """() => {
                document.querySelectorAll('.stx-ico-close').forEach(e => e.click());
                const overlay = document.querySelector('.ant-modal-wrap, .popup-overlay');
                if (overlay) overlay.click();
            }""")
            page.wait_for_timeout(500)
    except Exception:
        pass
    # 方法3: Playwright force click
    try:
        close_x = page.locator(".stx-ico-close")
        if close_x.count() > 0 and close_x.first.is_visible():
            close_x.first.click(force=True)
    except Exception:
        pass
    page.wait_for_timeout(300)


def _recover_to_trade_page(page, context):
    """检测页面是否离开了交易界面（登录页/空白页），如是则重新导航+登录。"""
    try:
        state = get_page_state(page)
        if state == "login":
            raise RuntimeError("on login page")
        # 额外检查 ant-select（交易下拉）是否存在
        if page.locator(".ant-select").count() == 0:
            raise RuntimeError("trade UI not found")
        return  # 页面正常，无需恢复
    except Exception as e:
        print(f"  [recovery] Detected bad page state ({e}), re-navigating...")

    try:
        page.goto(TRADE_URL, wait_until="domcontentloaded", timeout=TIMEOUT["navigation"])
        page.wait_for_timeout(2000)
    except Exception as nav_e:
        print(f"  [recovery] Navigation error: {nav_e}")
        return

    # 重新登录（如果需要）
    if page.locator('input[type="password"]').count() > 0:
        print("  [recovery] Re-logging in...")
        try:
            inputs = page.locator("input")
            inputs.nth(0).fill(ACCOUNT)
            inputs.nth(1).fill(PASSWORD)
            page.locator("button").filter(
                has_text=re.compile(r"log\s*in|login|sign", re.I)
            ).first.click()
            page.wait_for_timeout(2000)
            context.storage_state(path=str(AUTH_FILE))
            print("  [recovery] Re-login done")
        except Exception as login_e:
            print(f"  [recovery] Re-login error: {login_e}")
    # 等待交易 UI 加载
    try:
        page.get_by_role("button", name=re.compile(r"up|down", re.I)).first.wait_for(
            state="visible", timeout=8000
        )
    except Exception:
        page.wait_for_timeout(2000)


# ═══════════════════════════════════════
#  Login
# ═══════════════════════════════════════
def login(page, context):
    # Connection retry: up to 3 attempts
    for attempt in range(3):
        try:
            page.goto(TRADE_URL, wait_until="domcontentloaded", timeout=TIMEOUT["navigation"])
            break
        except Exception as e:
            if attempt < 2:
                print(f"[login] Connection attempt {attempt + 1} failed: {e}, retrying...")
                page.wait_for_timeout(3000)
            else:
                raise
    page.wait_for_timeout(DELAYS["page_load"])

    if page.locator('input[type="password"]').count() > 0:
        print("[login] Logging in...")
        inputs = page.locator("input")
        inputs.nth(0).fill(ACCOUNT)
        inputs.nth(1).fill(PASSWORD)
        page.locator("button").filter(
            has_text=re.compile(r"log\s*in|login|sign", re.I)
        ).first.click()
        page.wait_for_timeout(2000)
        context.storage_state(path=str(AUTH_FILE))
        print("[login] Done")
    else:
        print("[login] Session valid")

    # 等待交易区域加载（up/down 按钮）
    try:
        page.get_by_role("button", name=re.compile(r"up|down", re.I)).first.wait_for(
            state="visible", timeout=8000
        )
    except Exception:
        page.wait_for_timeout(1500)


# ═══════════════════════════════════════
#  Step 1: Select Currency + Verify
# ═══════════════════════════════════════
def select_currency(page, currency: str) -> bool:
    display = get_display(currency)
    print(f"  [currency] Selecting {display}...")

    # Guard: must be on trade page (not login page) before touching ant-select
    if page.locator('input[type="password"]').count() > 0:
        print("  [currency] WARN: still on login page, cannot select")
        return False

    variants = list(dict.fromkeys([
        display, display.upper(), display.lower(),
        display.capitalize(), display.title(),
    ]))

    def _open_dropdown() -> bool:
        """Open the currency dropdown. Returns True if dropdown appeared."""
        for sel in [".ant-select-selector", ".ant-select"]:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.click(force=True)
                    page.wait_for_timeout(250)
                    if page.locator(".ant-select-dropdown").count() > 0:
                        return True
            except Exception:
                pass
        # Last resort: JS click
        _safe_eval(page, """() => {
            const el = document.querySelector('.ant-select-selector')
                    || document.querySelector('.ant-select');
            if (el) el.click();
        }""")
        page.wait_for_timeout(300)
        try:
            return page.locator(".ant-select-dropdown").count() > 0
        except Exception:
            return False

    def _click_item_in_dom() -> bool:
        """Try to directly JS-click a matching item currently in the DOM."""
        return bool(_safe_eval(page, """(variants) => {
            const items = document.querySelectorAll(
                '.ant-select-item-option:not(.ant-select-item-option-disabled)');
            for (const item of items) {
                const title = (item.getAttribute('title') || '').trim();
                const text  = item.textContent.trim();
                for (const v of variants) {
                    if (title.toLowerCase() === v.toLowerCase()
                        || text.toLowerCase()  === v.toLowerCase()) {
                        item.click();
                        return true;
                    }
                }
            }
            return false;
        }""", variants, default=False))

    def _scroll_and_find(scroll_steps: int = 25) -> bool:
        """Scroll through virtual list to find item."""
        _safe_eval(page, """() => {
            const h = document.querySelector('.rc-virtual-list-holder')
                   || document.querySelector('.ant-select-dropdown');
            if (h && h.scrollTo) h.scrollTo({top: 0, behavior: 'instant'});
        }""")
        page.wait_for_timeout(100)
        for _ in range(scroll_steps):
            if _click_item_in_dom():
                return True
            # Also try Playwright title selector (catches items evaluate might miss)
            for variant in variants:
                try:
                    item = page.locator(f'.ant-select-item[title="{variant}"]')
                    if item.count() > 0:
                        item.first.click(force=True)
                        return True
                except Exception:
                    pass
            _safe_eval(page, """() => {
                const h = document.querySelector(
                    '.ant-select-dropdown .rc-virtual-list-holder')
                    || document.querySelector('.ant-select-dropdown');
                if (h) h.scrollBy({top: 90, behavior: 'instant'});
            }""")
            page.wait_for_timeout(DELAYS["dropdown_scroll"])
        return False

    def _try_once() -> bool:
        wait_for_loading_gone(page)
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)

        opened = _open_dropdown()
        if not opened:
            print("  [currency] Dropdown did not open, retrying...")
            page.wait_for_timeout(400)
            opened = _open_dropdown()
        if not opened:
            print("  [currency] Dropdown still not open")
            return False

        # Path 1: direct JS click (item already in DOM viewport)
        if _click_item_in_dom():
            return True

        # Path 2: scroll through virtual list
        if _scroll_and_find(scroll_steps=25):
            return True

        page.keyboard.press("Escape")
        return False

    # Up to 3 attempts, 500ms gap between
    for attempt in range(3):
        if attempt > 0:
            print(f"  [currency] Retry {attempt}...")
            page.wait_for_timeout(500)
        if _try_once():
            page.wait_for_timeout(200)
            try:
                selected = page.locator(".ant-select-selection-item").first
                actual = selected.text_content().strip() if selected.count() > 0 else ""
            except Exception:
                actual = ""
            if actual.upper() == display.upper():
                print(f"  [currency] ✓ Verified: {actual}")
                page.wait_for_timeout(DELAYS["spa_switch"])
                return True
            else:
                print(f"  [currency] Verify failed: got '{actual}', expected '{display}'")

    print(f"  [currency] FAIL: {display} not found after 3 attempts")
    return False
# ═══════════════════════════════════════
#  Step 2: Enter Amount + Verify
# ═══════════════════════════════════════
def enter_amount(page, amount: str) -> bool:
    print(f"  [amount] Setting {amount}...")
    wait_for_loading_gone(page)
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)

    inp = page.locator(
        'input:visible:not([type="password"]):not([type="hidden"])'
        ':not([readonly]):not([role="combobox"])'
    )

    def _find_target():
        for i in range(inp.count()):
            el = inp.nth(i)
            try:
                val = el.input_value()
                if re.match(r"^[\d,]*$", val):
                    return el
            except Exception:
                pass
        return inp.first if inp.count() > 0 else None

    # 最多重试 3 次（SPA 切币后可能 reset input）
    for attempt in range(3):
        for _ in range(8):
            if inp.count() > 0:
                break
            page.wait_for_timeout(300)

        target = _find_target()
        if not target:
            print("  [amount] FAIL: No editable input found")
            return False

        target.click(click_count=3)
        page.wait_for_timeout(100)
        page.keyboard.press(_SELECT_ALL)
        page.keyboard.press("Delete")
        page.wait_for_timeout(80)
        page.keyboard.type(amount, delay=30)
        page.wait_for_timeout(400)

        actual = target.input_value().replace(",", "")
        if actual == amount:
            print(f"  [amount] ✓ Verified: {actual}")
            return True
        elif attempt < 2:
            print(f"  [amount] Retry {attempt+1}: got '{actual}', expected {amount}")
            page.wait_for_timeout(500)
        else:
            print(f"  [amount] FAIL: Expected {amount}, got '{actual}'")
            return False
    return False


# ═══════════════════════════════════════
#  Step 3: Select Duration + Verify
# ═══════════════════════════════════════
def select_duration(page, duration: str) -> bool:
    dur_text = f"{duration}s"
    print(f"  [duration] Selecting {dur_text}...")

    clicked = page.evaluate("""(dur) => {
        const target = dur + 's';
        for (const el of document.querySelectorAll('*')) {
            const own = Array.from(el.childNodes)
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim()).join('');
            if (own === target) { el.click(); return true; }
        }
        for (const el of document.querySelectorAll('*')) {
            const t = el.textContent.trim();
            const r = el.getBoundingClientRect();
            if ((t === target || t.startsWith(target))
                && r.width > 20 && r.width < 150 && r.height < 60) {
                el.click(); return true;
            }
        }
        return false;
    }""", duration)

    if not clicked:
        btn = page.get_by_text(dur_text, exact=True)
        if btn.count() > 0:
            btn.first.click()
            clicked = True

    page.wait_for_timeout(300)

    if clicked:
        print(f"  [duration] ✓ Selected {dur_text}")
        return True
    else:
        print(f"  [duration] FAIL: {dur_text} not found")
        return False


# ═══════════════════════════════════════
#  Step 4: Click Direction + Verify ACTIVE
# ═══════════════════════════════════════
def click_direction(page, direction: str) -> bool:
    direction = direction.lower()
    d = direction.upper()
    print(f"  [direction] Clicking {d}...")

    def _do_click():
        """Try every method to click the UP/DOWN button."""
        # Method 1: role=button with exact text
        btn = page.get_by_role("button", name=re.compile(rf"^\s*{d}\s*$", re.I))
        if btn.count() > 0:
            btn.first.click(force=True)
            return
        # Method 2: class-based + text filter
        sel = ('[class*="up"], [class*="Up"], [class*="green"]'
               if direction == "up" else
               '[class*="down"], [class*="Down"], [class*="red"]')
        try:
            cls_btn = page.locator(sel).filter(has_text=re.compile(d, re.I)).first
            if cls_btn.count() > 0:
                cls_btn.click(force=True)
                return
        except Exception:
            pass
        # Method 3: JS scan — most reliable for SPA buttons
        _safe_eval(page, """(d) => {
            for (const el of document.querySelectorAll(
                    'button, [role="button"], div, span')) {
                if (el.textContent.trim().toUpperCase() === d
                        && el.offsetParent !== null) {
                    el.click(); return;
                }
            }
        }""", d)

    # Up to 3 click attempts — site occasionally needs a moment after amount entry
    for attempt in range(3):
        wait_for_loading_gone(page)
        _do_click()
        # Wait progressively longer on each attempt
        page.wait_for_timeout(700 + attempt * 400)
        state = get_page_state(page)
        if state == "active":
            print(f"  [direction] ✓ Order placed, trade ACTIVE (attempt {attempt+1})")
            return True
        if attempt < 2:
            print(f"  [direction] State '{state}' after attempt {attempt+1}, retrying...")

    print(f"  [direction] FAIL: Expected ACTIVE state after 3 attempts")
    return False


# ═══════════════════════════════════════
#  Step 5: Wait for Result + Close
# ═══════════════════════════════════════
def wait_for_result(page, duration: str, trade_start: float) -> dict:
    dur_sec = int(duration)
    # Must wait at least duration+5s from the moment the order was placed
    # before polling for result, to avoid capturing leftover/stale popups.
    wait_until = trade_start + dur_sec + 5.0
    max_wait_until = trade_start + dur_sec + 15.0  # absolute ceiling

    print(f"  [wait] Trade duration {dur_sec}s — waiting for expiry (≥{dur_sec+5}s)...")
    while time.time() < wait_until:
        time.sleep(0.5)

    print(f"  [wait] Expiry passed, polling for result popup...")
    result = {"won": False, "profit": "", "details": ""}

    while time.time() < max_wait_until:
        state = get_page_state(page)
        if state == "result":
            page.wait_for_timeout(500)
            result = page.evaluate("""() => {
                let won = false, profit = '', details = '';
                for (const el of document.querySelectorAll('*')) {
                    const m = el.textContent.trim()
                        .match(/Profit:\\s*(\\d+\\.?\\d*)/i);
                    if (m) {
                        profit = m[1];
                        won = parseFloat(profit) > 0;
                        break;
                    }
                }
                const rows = document.querySelectorAll('tr');
                for (const row of rows) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 4) {
                        details = Array.from(cells)
                            .map(c => c.textContent.trim()).join(' | ');
                        break;
                    }
                }
                return {won, profit, details};
            }""")

            status = "Won" if result["won"] else "Lost"
            print(f"  [result] {status} | Profit: {result.get('profit', '0')}")
            if result.get("details"):
                print(f"  [result] {result['details']}")

            shot(page, f"result-{int(time.time())}")
            _close_result_popup(page)
            print("  [result] Popup closed")

            # 确认回到 IDLE
            page.wait_for_timeout(300)
            final = get_page_state(page)
            if final != "idle":
                print(f"  [state] WARN: After close state={final}, retrying...")
                _close_result_popup(page)
                page.wait_for_timeout(300)
            return result

        page.wait_for_timeout(1000)

    print("  [warn] Result popup timeout")
    shot(page, f"timeout-{int(time.time())}")
    return result


def _safe_playwright():  # type: ignore[return]
    """Launch sync_playwright with retry on WinError 10055 socket exhaustion."""
    for attempt in range(3):
        try:
            # Force GC and close stale event loops before each attempt
            gc.collect()
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    asyncio.set_event_loop(asyncio.new_event_loop())
            except RuntimeError:
                asyncio.set_event_loop(asyncio.new_event_loop())
            return sync_playwright()
        except OSError as e:
            if "10055" in str(e) and attempt < 2:
                print(f"[init] Socket buffer exhausted, retrying ({attempt+1}/3)...")
                gc.collect()
                time.sleep(3)
            else:
                raise
    raise RuntimeError("_safe_playwright: all retries failed")


# ═══════════════════════════════════════
#  Main
# ═══════════════════════════════════════
def run(currency, amount, duration, direction, rounds):
    display = get_display(currency)
    d = direction.upper()

    print(f"\n{'='*40}")
    print(f"  Desktop Trade (Python + Chrome)")
    print(f"  Currency : {display}")
    print(f"  Amount   : {amount}")
    print(f"  Duration : {duration}s")
    print(f"  Direction: {d}")
    print(f"  Rounds   : {rounds}")
    print(f"{'='*40}\n")

    with _safe_playwright() as p:
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
            login(page, context)
            results = []

            for r in range(1, rounds + 1):
                print(f"\n=== Round {r}/{rounds}: "
                      f"{display} {amount} {d} {duration}s ===")

                # ── Step 0: 恢复页面 + 确保 IDLE ──
                _recover_to_trade_page(page, context)
                ensure_idle(page)

                # ── Step 1: 选币种（失败→恢复→重试一次）──
                if not select_currency(page, currency):
                    print("  [round] Currency failed, attempting page recovery...")
                    _recover_to_trade_page(page, context)
                    page.wait_for_timeout(500)
                    ensure_idle(page)
                    if not select_currency(page, currency):
                        raise RuntimeError(f"Currency {display} selection failed")

                # ── Step 2: 设金额 ──
                if not enter_amount(page, amount):
                    raise RuntimeError(f"Amount {amount} setting failed")

                # ── Step 3: 选时长 ──
                if not select_duration(page, duration):
                    raise RuntimeError(f"Duration {duration}s selection failed")

                # ── Step 4: 下单 ──
                if not click_direction(page, direction):
                    raise RuntimeError("Order placement failed")
                trade_start = time.time()

                # ── Step 5: 等待结算 ──
                result = wait_for_result(page, duration, trade_start)
                results.append(result)

                if r < rounds:
                    ensure_idle(page)
                    page.wait_for_timeout(300)

            # ── Summary ──
            print(f"\n{'='*40}")
            wins = sum(1 for r in results if r.get("won"))
            losses = len(results) - wins
            for i, r in enumerate(results):
                tag = "W" if r.get("won") else "L"
                print(f"  Round {i+1}: {tag} | "
                      f"Profit: {r.get('profit', '0')}")
            print(f"  Total: {wins}W / {losses}L")
            print(f"{'='*40}\n")

            print("===RESULT===")
            print(json.dumps({
                "status": "ok",
                "rounds": len(results),
                "wins": wins,
                "losses": losses,
                "screenshots": str(SCREENSHOT_DIR),
            }))
            print("===END===")

        except Exception as e:
            print(f"\n[error] {e}")
            shot(page, "error")
            print("===RESULT===")
            print(json.dumps({"status": "error", "message": str(e)}))
            print("===END===")
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BPTrading Desktop Trade")
    parser.add_argument("--currency", default=TRADE_DEFAULTS["currency"])
    parser.add_argument("--amount", default=TRADE_DEFAULTS["amount"])
    parser.add_argument("--duration", default=TRADE_DEFAULTS["duration"])
    parser.add_argument("--direction", default=TRADE_DEFAULTS["direction"])
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()
    run(args.currency, args.amount, args.duration, args.direction, args.rounds)
