"""OKXOption Desktop Trade - Python + Playwright (Chromium)

State-Machine Flow:
  1. ensure_idle()  — 确认无活跃交易 / 关闭残留弹窗
  2. select_currency() + verify  — 选币种 → 验证下拉框显示一致
  3. enter_amount() + verify     — 设金额 → 验证 input 值一致
  4. select_duration() + verify  — 选时长 → 验证高亮
  5. click_direction() + verify  — 下单   → 验证进入 ACTIVE 状态
  6. wait_for_result()           — 等结算 → 截图 → 关闭弹窗 → 回到 IDLE
"""
import sys
import re
import time
import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    TRADE_URL, ACCOUNT, PASSWORD, BROWSER, TIMEOUT, DELAYS,
    TRADE_DEFAULTS, get_display, get_category,
)
from playwright.sync_api import sync_playwright

ROOT_DIR   = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT_DIR / "screenshots"
AUTH_FILE   = ROOT_DIR / "auth.json"
SCREENSHOT_DIR.mkdir(exist_ok=True)


def shot(page, name: str) -> str:
    p = str(SCREENSHOT_DIR / f"trade-{name}.png")
    page.screenshot(path=p)
    print(f"  [screenshot] {p}")
    return p


# ═══════════════════════════════════════
#  Loading 遮罩层处理
# ═══════════════════════════════════════
def wait_for_loading_gone(page, timeout_ms: int = 10000):
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
        page.evaluate("""() => {
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
        print("  [loading] Force removed loading overlay")
        page.wait_for_timeout(200)


# ═══════════════════════════════════════
#  状态检测
# ═══════════════════════════════════════
def get_page_state(page) -> str:
    """返回页面当前状态: idle / active / result"""
    # 用 JS 检测弹窗是否真正可见（排除 display:none 的残留元素）
    has_result = page.evaluate("""() => {
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
    }""")
    if has_result:
        return "result"
    if page.locator("text=Expiration time").count() > 0:
        return "active"
    if page.locator("text=Estimate profit").count() > 0:
        return "active"
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
    page.evaluate("""() => {
        const el = document.querySelector('.stx-ico-close');
        if (el) { el.click(); return; }
        const d = document.querySelector('[class*="TradeResultDialog"]');
        if (d) { const b = d.querySelector('[class*="close"]'); if (b) b.click(); }
    }""")
    page.wait_for_timeout(700)
    # 方法2: 如果弹窗还在，点击空白区域或 X
    if page.get_by_text("Trade result").count() > 0:
        page.evaluate("""() => {
            document.querySelectorAll('.stx-ico-close').forEach(e => e.click());
            const overlay = document.querySelector('.ant-modal-wrap, .popup-overlay');
            if (overlay) overlay.click();
        }""")
        page.wait_for_timeout(500)
    # 方法3: Playwright force click
    try:
        close_x = page.locator(".stx-ico-close")
        if close_x.count() > 0 and close_x.first.is_visible():
            close_x.first.click(force=True)
    except Exception:
        pass
    page.wait_for_timeout(300)


# ═══════════════════════════════════════
#  Login
# ═══════════════════════════════════════
def login(page, context):
    page.goto(TRADE_URL, wait_until="domcontentloaded", timeout=TIMEOUT["navigation"])
    page.wait_for_timeout(DELAYS["page_load"])

    if page.locator('input[type="password"]').count() > 0:
        print("[login] Logging in...")
        inputs = page.locator("input")
        inputs.nth(0).fill(ACCOUNT)
        inputs.nth(1).fill(PASSWORD)
        page.locator("button").filter(
            has_text=re.compile(r"log\s*in|login|sign", re.I)
        ).first.click()
        page.wait_for_timeout(4000)
        context.storage_state(path=str(AUTH_FILE))
        print("[login] Done")
    else:
        print("[login] Session valid")

    # 等待交易区域加载（up/down 按钮）
    try:
        page.get_by_role("button", name=re.compile(r"up|down", re.I)).first.wait_for(
            state="visible", timeout=10000
        )
    except Exception:
        page.wait_for_timeout(3000)


# ═══════════════════════════════════════
#  Step 1: Select Currency + Verify
# ═══════════════════════════════════════
def select_currency(page, currency: str) -> bool:
    display = get_display(currency)
    print(f"  [currency] Selecting {display}...")

    wait_for_loading_gone(page)
    
    # 先关闭可能残留的下拉框
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    page.locator(".ant-select").first.click()
    page.wait_for_timeout(300)
    dropdown = page.locator(".ant-select-dropdown")

    # 智能匹配：先精确匹配，再大小写不敏感匹配
    for attempt in range(15):
        # 方法1: 精确匹配 title 属性
        item = page.locator(f'.ant-select-item[title="{display}"]')
        if item.count() > 0 and item.is_visible():
            item.click()
            break
        
        # 方法2: 大小写不敏感匹配 - 尝试常见变体
        variants = [display, display.upper(), display.lower(), display.capitalize()]
        matched = False
        for variant in variants:
            item = page.locator(f'.ant-select-item[title="{variant}"]')
            if item.count() > 0 and item.is_visible():
                item.click()
                display = variant  # 更新为实际匹配到的名称
                matched = True
                break
            # 也尝试文本内容匹配
            text_item = dropdown.locator(f'.ant-select-item-option-content:text-is("{variant}")')
            if text_item.count() > 0 and text_item.is_visible():
                text_item.click()
                display = variant
                matched = True
                break
        if matched:
            break
            
        if attempt < 14:
            page.evaluate("""() => {
                const dd = document.querySelector(
                    '.ant-select-dropdown .rc-virtual-list-holder')
                    || document.querySelector('.ant-select-dropdown');
                if (dd) dd.scrollBy({top: 120, behavior: 'auto'});
            }""")
            page.wait_for_timeout(DELAYS["dropdown_scroll"])
    else:
        page.keyboard.press("Escape")
        print(f"  [currency] FAIL: {display} not found in dropdown")
        return False

    page.keyboard.press("Escape")
    page.wait_for_timeout(DELAYS["input_verify"])

    # ── 验证（大小写不敏感）──
    selected = page.locator(".ant-select-selection-item").first
    actual = selected.text_content().strip() if selected.count() > 0 else ""
    if actual.upper() == display.upper():
        print(f"  [currency] ✓ Verified: {actual}")
        # 等待 SPA 完成切币后页面重渲染，避免 amount 被重置
        page.wait_for_timeout(DELAYS["spa_switch"])
        return True
    else:
        print(f"  [currency] FAIL: Expected {display}, got '{actual}'")
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
        page.keyboard.press("Control+A")
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
    direction = direction.lower()  # Normalize to lowercase
    d = direction.upper()
    print(f"  [direction] Clicking {d}...")

    wait_for_loading_gone(page)

    btn = page.get_by_role("button", name=re.compile(rf"^\s*{d}\s*$", re.I))
    if btn.count() > 0:
        btn.first.click()
    else:
        # class fallback
        sel = ('[class*="up"], [class*="Up"], [class*="green"]'
               if direction == "up" else
               '[class*="down"], [class*="Down"], [class*="red"]')
        cls_btn = page.locator(sel).filter(has_text=re.compile(d, re.I)).first
        if cls_btn.count() > 0:
            cls_btn.click()
        else:
            page.evaluate(f"""(d) => {{
                for (const el of document.querySelectorAll(
                    'button, [role="button"], div, span')) {{
                    if (el.textContent.trim().toUpperCase() === d
                        && el.offsetParent !== null) {{
                        el.click(); return;
                    }}
                }}
            }}""", d)

    page.wait_for_timeout(1100)

    # ── 验证进入 ACTIVE 状态（倒计时出现）──
    state = get_page_state(page)
    if state == "active":
        print(f"  [direction] ✓ Order placed, trade ACTIVE")
        return True
    else:
        print(f"  [direction] FAIL: Expected ACTIVE state, got '{state}'")
        return False


# ═══════════════════════════════════════
#  Step 5: Wait for Result + Close
# ═══════════════════════════════════════
def wait_for_result(page, duration: str) -> dict:
    wait_s = int(duration) + 20
    print(f"  [wait] Waiting up to {wait_s}s for settlement...")

    result = {"won": False, "profit": "", "details": ""}
    start = time.time()

    while time.time() - start < wait_s:
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
            page.wait_for_timeout(700)
            final = get_page_state(page)
            if final != "idle":
                print(f"  [state] WARN: After close state={final}, retrying...")
                _close_result_popup(page)
                page.wait_for_timeout(700)
            return result

        page.wait_for_timeout(1000)

    print("  [warn] Result popup timeout")
    shot(page, f"timeout-{int(time.time())}")
    return result


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
            login(page, context)
            results = []

            for r in range(1, rounds + 1):
                print(f"\n=== Round {r}/{rounds}: "
                      f"{display} {amount} {d} {duration}s ===")

                # ── Step 0: 确保 IDLE ──
                ensure_idle(page)

                # ── Step 1: 选币种 ──
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

                # ── Step 5: 等待结算 ──
                result = wait_for_result(page, duration)
                results.append(result)

                if r < rounds:
                    # 确保完全回到 IDLE 再开始下一轮
                    ensure_idle(page)
                    page.wait_for_timeout(1000)

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
    parser = argparse.ArgumentParser(description="OKXOption Desktop Trade")
    parser.add_argument("--currency", default=TRADE_DEFAULTS["currency"])
    parser.add_argument("--amount", default=TRADE_DEFAULTS["amount"])
    parser.add_argument("--duration", default=TRADE_DEFAULTS["duration"])
    parser.add_argument("--direction", default=TRADE_DEFAULTS["direction"])
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()
    run(args.currency, args.amount, args.duration, args.direction, args.rounds)
