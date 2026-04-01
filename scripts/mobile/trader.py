"""OKXOption Mobile Trade - Python + Playwright (Chromium iPhone Emulation)

State-Machine Flow:
  1. desktop_login()   — Phase 1: Chromium 桌面登录 → 保存 session
  2. mobile_open()     — Phase 2: Chromium iPhone 模拟 → 加载 session
  3. ensure_idle()     — 确认无活跃交易 / 关闭残留弹窗
  4. select_currency() + verify  — 选币种 → 验证跳转到 chart 页
  5. enter_amount() + verify     — 设金额 → 验证 input 值
  6. select_duration() + verify  — 选时长 → 验证显示
  7. click_direction() + verify  — 下单   → 验证进入 ACTIVE 状态
  8. wait_for_result()           — 等结算 → 截图 → 关闭弹窗 → 回到 IDLE
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

ROOT_DIR       = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT_DIR / "screenshots"
AUTH_FILE       = ROOT_DIR / "auth.json"
SCREENSHOT_DIR.mkdir(exist_ok=True)

IPHONE = {
    "viewport": {"width": 430, "height": 932},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
}


def shot(page, name: str) -> str:
    ts = int(time.time())
    p = str(SCREENSHOT_DIR / f"mobile-{name}-{ts}.png")
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
                // 常见 loading 选择器
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
        # 强制移除 loading 遮罩
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
        page.wait_for_timeout(300)


# ═══════════════════════════════════════
#  状态检测
# ═══════════════════════════════════════
def get_page_state(page) -> str:
    """返回页面当前状态: idle / active / result"""
    if page.get_by_text(re.compile(
            r"Settlement Completed|结算完成", re.I)).count() > 0:
        return "result"
    if page.locator("text=Expiration time").count() > 0:
        return "active"
    if page.locator("text=Estimate profit").count() > 0:
        return "active"
    return "idle"


def ensure_idle(page, timeout_s: int = 120):
    """确保页面处于 IDLE 状态。活跃交易则等待; 结果弹窗则关闭。超时 2 分钟。"""
    state = get_page_state(page)
    if state == "idle":
        return

    if state == "result":
        print("  [state] Closing leftover result popup...")
        _close_result_popup(page)
        page.wait_for_timeout(700)
        return

    # state == "active"
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
    # 方法1: JS 直接点击 Confirm 或关闭按钮（绕过可见性限制）
    closed = page.evaluate("""() => {
        for (const el of document.querySelectorAll('button, span, div, a')) {
            const t = el.textContent.trim();
            if (t === 'Confirm' || t === '确认') { el.click(); return true; }
        }
        const x = document.querySelector('.stx-ico-close');
        if (x) { x.click(); return true; }
        return false;
    }""")
    page.wait_for_timeout(500)
    if not closed:
        # 方法2: Playwright force tap
        try:
            confirm = page.get_by_text("Confirm", exact=True)
            if confirm.count() > 0:
                confirm.first.tap(force=True, timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(300)


def _dismiss_blocking_popup(page):
    """Dismiss market-closed / generic blocking modal safely."""
    page.evaluate("""() => {
        // First try pressing the visible Back button on white popup
        for (const el of document.querySelectorAll('button, div, span, a')) {
            const t = (el.textContent || '').trim();
            if (t === 'Back' || t === '返回') {
                const r = el.getBoundingClientRect();
                if (r.width > 40 && r.height > 20) {
                    el.click();
                    return;
                }
            }
        }

        // Fallback: remove common overlay/modal nodes that block touches
        for (const sel of [
            '.van-overlay', '.van-popup', '.van-dialog',
            '.ant-modal-wrap', '.ant-modal-mask'
        ]) {
            for (const n of document.querySelectorAll(sel)) {
                n.remove();
            }
        }

        // Legacy close button
        const b = document.querySelector('.popback');
        if (b) b.click();
    }""")
    page.wait_for_timeout(400)


# ═══════════════════════════════════════
#  Phase 1: Desktop Login
# ═══════════════════════════════════════
def desktop_login(playwright):
    print("[phase1] Desktop login via Chromium...")
    browser = playwright.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(TRADE_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    if page.locator('input[type="password"]').count() > 0:
        print("  [login] Filling credentials...")
        inputs = page.locator("input")
        inputs.nth(0).fill(ACCOUNT)
        inputs.nth(1).fill(PASSWORD)
        page.locator("button").first.click()
        page.wait_for_timeout(5000)
        print("  [login] Done")
    else:
        print("  [login] Session valid")

    ctx.storage_state(path=str(AUTH_FILE))
    print(f"  [session] Saved to {AUTH_FILE}")
    browser.close()


# ═══════════════════════════════════════
#  Phase 2: Mobile Browser
# ═══════════════════════════════════════

# Global settlement data captured from network responses
_network_settlement = {"detected": False, "won": None, "profit": "", "raw": ""}

def _on_response(response):
    """Intercept network responses to detect settlement results."""
    global _network_settlement
    if _network_settlement["detected"]:
        return
    try:
        url = response.url
        # Only match the actual settlement endpoint: getResult?tradeId=
        if "getResult" not in url:
            return
        ct = response.headers.get("content-type", "")
        if "json" not in ct:
            return
        body = response.json()
        raw = json.dumps(body)
        print(f"  [net] Settlement response from: {url[:80]}")
        print(f"  [net] Body snippet: {raw[:300]}")
        _network_settlement["raw"] = raw[:1000]
        _network_settlement["detected"] = True
        # Parse result field: 1=win, 2=loss (OKX convention)
        msg = body.get("msg", {})
        result_code = msg.get("result")
        if result_code == 1:
            _network_settlement["won"] = True
        elif result_code == 2:
            _network_settlement["won"] = False
        # Parse profit from closedAmount/resultAmount
        closed = msg.get("closedAmount", 0)
        if closed and float(closed) > 0:
            _network_settlement["profit"] = str(closed)
    except Exception:
        pass


def mobile_open(playwright):
    global _network_settlement
    _network_settlement = {"detected": False, "won": None, "profit": "", "raw": ""}
    print("[phase2] Opening mobile viewport (iPhone emulation)...")
    browser = playwright.chromium.launch(
        headless=BROWSER["headless"], slow_mo=80,
    )
    ctx = browser.new_context(
        **IPHONE, locale="zh-CN",
        storage_state=str(AUTH_FILE) if AUTH_FILE.exists() else None,
    )
    page = ctx.new_page()
    # 注入脚本隐藏 webdriver 标记，防止被检测为自动化
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page.on("response", _on_response)
    page.goto(TRADE_URL, wait_until="domcontentloaded", timeout=45000)

    # 等待页面元素出现
    try:
        page.locator(
            'input[type="password"], .list-title, .van-overlay, .down-btn'
        ).first.wait_for(state="visible", timeout=15000)
    except Exception:
        page.wait_for_timeout(5000)

    # 登录检测
    url = page.url
    is_login = ("#/login" in url or "/login" in url
                or page.locator('input[type="password"]').count() > 0
                or page.get_by_text("Log In", exact=True).count() > 0)

    if is_login:
        print("  [warn] Login required")
        try:
            page.locator('input[type="password"]').wait_for(
                state="visible", timeout=10000)
        except Exception:
            page.reload(wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)

        inputs = page.locator("input")
        if inputs.count() >= 2:
            inputs.nth(0).fill(ACCOUNT)
            inputs.nth(1).fill(PASSWORD)
        elif inputs.count() == 1:
            inputs.nth(0).fill(ACCOUNT)
            page.wait_for_timeout(1000)
            pwd = page.locator('input[type="password"]')
            if pwd.count() > 0:
                pwd.first.fill(PASSWORD)

        page.evaluate("""() => {
            const btn = document.querySelector('.loginbtm')
                     || document.querySelector('button');
            if (btn) btn.click();
        }""")
        page.wait_for_timeout(5000)
        page.goto(TRADE_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)
        print("  [login] Mobile login completed")
    else:
        print("  [session] Session valid")

    return browser, ctx, page


# ═══════════════════════════════════════
#  Close Market Popup
# ═══════════════════════════════════════
def close_market_popup(page):
    _dismiss_blocking_popup(page)


# ═══════════════════════════════════════
#  Step 1: Select Currency + Verify
# ═══════════════════════════════════════
def select_currency(page, currency: str) -> bool:
    display = get_display(currency)
    category = get_category(currency)
    print(f"  [currency] Selecting {display} ({category})...")

    close_market_popup(page)

    # 每次都强制刷新 trade 页面（确保滚动位置重置到顶部）
    page.goto(TRADE_URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(DELAYS["popup_check"])
    page.reload(wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(DELAYS["page_load"])
    # 滚动到页面顶部，确保从 Cryptocurrency Trade 开始
    page.evaluate("() => { (document.scrollingElement || document.body).scrollTo(0, 0); }")
    page.wait_for_timeout(DELAYS["input_verify"])
    close_market_popup(page)

    # 切换分类 tab
    if category != "crypto":
        tab_map = {
            "forex": ["Forex", "FX", "外汇"],
            "commodities": ["Commodities", "商品", "Gold"],
            "indices": ["Indices", "指数"],
        }
        page.evaluate("""(texts) => {
            for (const text of texts) {
                for (const el of document.querySelectorAll(
                    'div, span, button, a')) {
                    const c = el.textContent.trim();
                    if (c === text || c.includes(text)) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 30 && r.width < 200
                            && r.height > 20 && r.height < 80) {
                            el.click(); return;
                        }
                    }
                }
            }
        }""", tab_map.get(category, [category]))
        page.wait_for_timeout(1200)

    # 找到并点击币种行
    navigated = False
    # 先向上滚动到顶部（尝试多种滚动容器）
    page.evaluate("""() => {
        (document.scrollingElement || document.body).scrollTo(0, 0);
        document.querySelectorAll('div, section').forEach(el => {
            if (el.scrollHeight > el.clientHeight + 50 && el.clientHeight > 300) {
                el.scrollTo(0, 0);
            }
        });
        window.scrollTo(0, 0);
    }""")
    page.wait_for_timeout(800)

    # 大小写不敏感：尝试多种变体 e.g. ["BTC", "btc", "Btc"]
    search_texts = list({display, display.upper(), display.lower(), display.capitalize(), currency.upper(), currency.lower()})
    for attempt in range(12):
        if attempt == 0:
            close_market_popup(page)
        spans = page.locator("span, div").all()
        for el in spans:
            try:
                text = el.text_content().strip()
                if text not in search_texts:
                    continue
                box = el.bounding_box()
                if box and box["height"] > 20 and box["y"] >= 0:
                    parent = el.locator("xpath=..").first
                    parent.tap()
                    navigated = True
                    break
            except Exception:
                continue
        if navigated:
            break
        if attempt < 11:
            # First half: scroll down, second half: scroll up
            direction = 300 if attempt < 6 else -300
            page.evaluate(f"""() => {{
                const c = document.scrollingElement || document.body;
                c.scrollBy({{top: {direction}, behavior: 'smooth'}});
                window.scrollBy({{top: {direction}, behavior: 'smooth'}});
            }}""")
            page.wait_for_timeout(700)

    if not navigated:
        print(f"  [currency] FAIL: {display} not found in market list")
        return False

    print(f"  [currency] Tapped {display}")

    # ── 验证跳转到 chart 页面 ──
    try:
        page.wait_for_url(re.compile(r"#/chart"), timeout=10000)
    except Exception:
        print(f"  [currency] FAIL: Did not navigate to chart page")
        return False

    # ── 验证交易面板加载完成 ──
    try:
        page.locator(".amount-btn, .amount-box, .down-btn, .up-btn").first \
            .wait_for(state="visible", timeout=15000)
    except Exception:
        print(f"  [currency] FAIL: Trade panel not loaded")
        return False

    page.wait_for_timeout(700)
    print(f"  [currency] ✓ Trade panel loaded for {display}")
    return True


# ═══════════════════════════════════════
#  Step 2: Enter Amount + Verify
# ═══════════════════════════════════════
def enter_amount(page, amount: str) -> bool:
    print(f"  [amount] Setting {amount}...")

    close_market_popup(page)
    wait_for_loading_gone(page)

    inp = page.locator(".amount-btn input, .amount-box input").first
    try:
        inp.wait_for(state="visible", timeout=15000)
    except Exception:
        print("  [amount] FAIL: Amount input not found")
        return False

    for attempt in range(3):
        # Clear via JS (mobile doesn't reliably handle Ctrl+A)
        page.evaluate("""(val) => {
            const inp = document.querySelector('.amount-btn input, .amount-box input');
            if (!inp) return;
            const nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            nativeSetter.call(inp, val);
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
        }""", amount)
        page.wait_for_timeout(400)

        # Verify
        actual = inp.input_value().replace(",", "")
        if actual == amount:
            print(f"  [amount] ✓ Verified: {actual}")
            return True

        print(f"  [amount] Attempt {attempt + 1}: expected {amount}, got '{actual}', retrying...")
        page.wait_for_timeout(500)

    print(f"  [amount] FAIL: Could not set amount after 3 attempts")
    return False


# ═══════════════════════════════════════
#  Step 3: Select Duration + Verify
# ═══════════════════════════════════════
def select_duration(page, duration: str) -> bool:
    dur_text = f"{duration}s"
    print(f"  [duration] Selecting {dur_text}...")

    close_market_popup(page)
    wait_for_loading_gone(page)

    tc = page.locator(".time-content").first
    if tc.count() == 0:
        print("  [duration] FAIL: .time-content not found")
        return False

    tc.tap()
    page.wait_for_timeout(1000)

    selected = page.evaluate("""(target) => {
        const popup = document.querySelector('.time-pop');
        if (!popup) return 'no-popup';
        for (const s of popup.querySelectorAll('span')) {
            if (s.textContent.trim() === target) { s.click(); return 'ok'; }
        }
        const num = target.replace('s', '');
        for (const s of popup.querySelectorAll('span')) {
            if (s.textContent.trim().startsWith(num)) {
                s.click(); return 'ok';
            }
        }
        return 'not-found';
    }""", dur_text)

    if selected == "no-popup":
        # 重试一次
        tc.tap()
        page.wait_for_timeout(1500)
        selected = page.evaluate("""(target) => {
            const popup = document.querySelector('.time-pop');
            if (!popup) return 'no-popup';
            for (const s of popup.querySelectorAll('span')) {
                if (s.textContent.trim() === target) {
                    s.click(); return 'ok';
                }
            }
            return 'not-found';
        }""", dur_text)

    page.wait_for_timeout(700)
    time_display = page.locator(".time-content .time, .time-content").first \
        .text_content().strip()
    if duration in time_display:
        print(f"  [duration] ✓ Verified: {time_display}")
        return True
    elif selected == "ok":
        print(f"  [duration] ✓ Selected {dur_text} (display: {time_display})")
        return True
    else:
        print(f"  [duration] FAIL: {dur_text} not found (display: {time_display})")
        return False


# ═══════════════════════════════════════
#  Step 4: Click Direction + Verify ACTIVE
# ═══════════════════════════════════════
def click_direction(page, direction: str):
    """Return trade start timestamp (float) on success, 0.0 on failure."""
    direction = direction.lower()  # Normalize to lowercase
    cls = ".up-btn" if direction == "up" else ".down-btn"
    print(f"  [direction] Tapping {direction.upper()}...")

    close_market_popup(page)
    wait_for_loading_gone(page)

    btn = page.locator(cls).first
    try:
        btn.wait_for(state="visible", timeout=10000)
        btn.tap()
    except Exception:
        try:
            page.get_by_text(re.compile(
                rf"^\s*{direction}\s*$", re.I)).last.tap(timeout=5000)
        except Exception:
            print(f"  [direction] FAIL: {direction.upper()} button not found")
            return 0.0

    page.wait_for_timeout(1300)

    # ── 验证进入 ACTIVE 状态 ──
    state = get_page_state(page)
    if state == "active":
        trade_start = time.time()
        print(f"  [direction] ✓ Order placed, trade ACTIVE")
        # 立即安装 MutationObserver 捕获结算弹窗
        _install_settlement_observer(page)
        return trade_start
    else:
        print(f"  [direction] FAIL: Expected ACTIVE, got '{state}'")
        return 0.0


def _install_settlement_observer(page):
    """Install observer + setInterval to catch settlement popups immediately."""
    page.evaluate("""() => {
        window.__settlementDetected = false;
        window.__settlementText = '';
        window.__settlementHTML = '';

        const POPUP_SELECTORS = [
            '.result-pop', '.win-pop', '.lose-pop', '.settle-pop',
            '.result-modal', '.trade-result', '.order-result',
            '[class*="result-pop"]', '[class*="settle"]',
            '[class*="ResultPop"]', '[class*="SettlePop"]',
        ];
        const TEXT_RE = /Settlement Completed|\u7ed3\u7b97\u5b8c\u6210|You\\s*Won|You\\s*Lost|\u4f60\u8d62\u4e86|\u4f60\u8f93\u4e86|\u76c8\u5229|\u4e8f\u635f|win|lose/i;

        const capture = () => {
            if (window.__settlementDetected) return;
            // 策略1: 按弹窗 class 查找
            for (const sel of POPUP_SELECTORS) {
                try {
                    const el = document.querySelector(sel);
                    if (el) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            window.__settlementDetected = true;
                            window.__settlementHTML = el.outerHTML.substring(0, 5000);
                            window.__settlementText = (el.innerText || el.textContent || '').substring(0, 1000);
                            return;
                        }
                    }
                } catch(e) {}
            }
            // 策略2: 扫描所有可见 div/section 找结算关键词
            const candidates = document.querySelectorAll(
                'div[class*="pop"], div[class*="modal"], div[class*="dialog"], '
                + 'div[class*="result"], div[class*="settle"], section[class*="pop"]'
            );
            for (const el of candidates) {
                const r = el.getBoundingClientRect();
                if (r.width < 50 || r.height < 50) continue;
                const txt = el.innerText || el.textContent || '';
                if (TEXT_RE.test(txt)) {
                    window.__settlementDetected = true;
                    window.__settlementHTML = el.outerHTML.substring(0, 5000);
                    window.__settlementText = txt.substring(0, 1000);
                    return;
                }
            }
            // 策略3: 全页文本兜底
            const bodyTxt = document.body ? (document.body.innerText || '') : '';
            if (TEXT_RE.test(bodyTxt)) {
                window.__settlementDetected = true;
                window.__settlementText = bodyTxt.substring(0, 2000);
            }
        };

        // 立即检查一次
        capture();

        // MutationObserver: DOM 变化时检查
        const obs = new MutationObserver(capture);
        obs.observe(document.body, {
            childList: true, subtree: true, attributes: true
        });

        // setInterval 每 80ms 主动扫描 (防止 MutationObserver 漏报)
        window.__settlementTimer = setInterval(() => {
            capture();
            if (window.__settlementDetected) {
                clearInterval(window.__settlementTimer);
                obs.disconnect();
            }
        }, 80);
    }""")


# ═══════════════════════════════════════
# ═══════════════════════════════════════
#  Step 5: Wait for Result + Close
# ═══════════════════════════════════════
def _read_balance(page) -> float:
    """Read the current account balance shown in the page header."""
    try:
        raw = page.evaluate("""() => {
            // Strategy 1: known class selectors
            const SELS = [
                '.user-balance', '.account-balance', '.wallet-balance',
                '[class*="balance"]'
            ];
            for (const s of SELS) {
                const el = document.querySelector(s);
                if (el) {
                    const t = (el.innerText || el.textContent || '').trim();
                    const m = t.match(/[\d,]+\.?\d*/);
                    if (m) return m[0];
                }
            }
            // Strategy 2: scan body text for "Balance" label
            const body = document.body ? (document.body.innerText || '') : '';
            const m = body.match(/Balance[^\d]*\$?([\d,]+\.?\d*)/i);
            return m ? m[1] : '';
        }""")
        if raw:
            return float(str(raw).replace(',', '').strip())
    except Exception:
        pass
    return 0.0


def _is_countdown_visible(page) -> bool:
    """True while a trade is active (countdown is displayed)."""
    try:
        return page.evaluate("""() => {
            const t = document.body ? (document.body.innerText || '') : '';
            // Active trade shows "Expiration time" + mm:ss
            if (/Expiration\\s*time/i.test(t)) return true;
            // Also matches visible countdown spans like "00:45"
            for (const el of document.querySelectorAll('span, div')) {
                if (/^\\d{2}\\s*:\\s*\\d{2}$/.test((el.innerText||'').trim())) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 10 && r.height > 10) return true;
                }
            }
            return false;
        }""")
    except Exception:
        return True   # assume active on error


def _parse_win_loss(initial: float, final: float, popup_text: str) -> dict:
    """Determine won/lost and profit from balance change or popup text."""
    if initial > 0 and final > 0 and abs(final - initial) > 0.1:
        won = final > initial
        profit = f"{abs(final - initial):.2f}".rstrip("0").rstrip(".")
        return {"won": won, "profit": profit}
    # Strict text fallback (no false-positive on "Estimate profit")
    import re as _re
    t = popup_text.lower()
    won = bool(_re.search(r"you\s*won|you\s*win|\bwon\b|\u8d62\u4e86|\u76c8\u5229\u4e86", t))
    lost = bool(_re.search(r"you\s*lost|you\s*lose|\blost\b|\u8f93\u4e86|\u4e8f\u635f\u4e86", t))
    if lost:
        won = False
    profit = ""
    m = _re.search(r"profit[:\s]+([\d,]+\.?\d*)", t)
    if m:
        profit = m.group(1).replace(",", "")
    return {"won": won, "profit": profit}


def wait_for_result(page, duration: str, r: int, trade_start: float) -> dict:
    global _network_settlement
    dur_sec = int(duration)
    expiry_at = trade_start + dur_sec
    print(f"  [wait] Trade duration {dur_sec}s — waiting for expiry...")

    initial_balance = _read_balance(page)
    if initial_balance:
        print(f"  [balance] Before: ${initial_balance:,.2f}")

    # Reset network settlement detector for this round
    _network_settlement = {"detected": False, "won": None, "profit": "", "raw": ""}

    result = {"won": False, "profit": "", "texts": ""}

    # Wait until expiry + a few seconds for settlement
    wait_until = expiry_at + 3.0
    while time.time() < wait_until:
        # Check network settlement early
        if _network_settlement["detected"]:
            print(f"  [net] Settlement captured from network API!")
            print(f"  [net] Raw: {_network_settlement['raw'][:200]}")
            break
        remaining = wait_until - time.time()
        time.sleep(min(0.5, max(0, remaining)))

    # Wait a bit more for balance to update
    time.sleep(2)

    final_balance = _read_balance(page)

    # Take ONE final screenshot
    shot(page, f"trade-result-r{r}")

    page.evaluate("() => { if(window.__settlementTimer) clearInterval(window.__settlementTimer); }")

    # Determine result: network API > balance > undetermined
    if _network_settlement["detected"]:
        won = _network_settlement["won"]
        profit = _network_settlement["profit"]
        if won is None:
            # Can't determine from network body alone, try balance
            if not final_balance:
                final_balance = _read_balance(page)
            if initial_balance and final_balance and abs(final_balance - initial_balance) > 0.1:
                won = final_balance > initial_balance
                profit = f"{abs(final_balance - initial_balance):.2f}".rstrip("0").rstrip(".")
            else:
                won = False
        texts = f"network: {_network_settlement['raw'][:100]}"
    elif final_balance and initial_balance and abs(final_balance - initial_balance) > 0.1:
        won = final_balance > initial_balance
        profit = f"{abs(final_balance - initial_balance):.2f}".rstrip("0").rstrip(".")
        texts = f"balance: {initial_balance}->{final_balance}"
    else:
        # Last resort: navigate fresh to get updated balance
        print("  [settle] No result detected — navigating fresh for balance...")
        try:
            page.goto(TRADE_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"  [warn] Navigation error: {e}")
        final_balance = _read_balance(page)
        shot(page, f"trade-result-final-r{r}")
        if initial_balance and final_balance and abs(final_balance - initial_balance) > 0.1:
            won = final_balance > initial_balance
            profit = f"{abs(final_balance - initial_balance):.2f}".rstrip("0").rstrip(".")
        else:
            won = False
            profit = ""
            print("  [warn] Could not determine result")
        texts = f"balance: {initial_balance}->{final_balance}"

    if final_balance:
        print(f"  [balance] After: ${final_balance:,.2f}")

    result["won"] = won
    result["profit"] = profit
    result["texts"] = texts

    status = "Won" if won else "Lost"
    print(f"  [result] {status} | Profit: {profit}")
    return result


def run(currency, amount, duration, direction, rounds):
    display = get_display(currency)

    print(f"\n{'='*40}")
    print(f"  Mobile Trade (Python + Chrome)")
    print(f"  Currency : {display}")
    print(f"  Amount   : {amount}")
    print(f"  Duration : {duration}s")
    print(f"  Direction: {direction.upper()}")
    print(f"  Rounds   : {rounds}")
    print(f"{'='*40}\n")

    with sync_playwright() as p:
        desktop_login(p)
        browser, ctx, page = mobile_open(p)

        MAX_RETRIES = 3
        results = []
        try:
            for r in range(1, rounds + 1):
                print(f"\n=== Round {r}/{rounds}: "
                      f"{display} {amount} {direction.upper()} "
                      f"{duration}s ===")

                last_err = None
                for retry in range(MAX_RETRIES):
                    if retry > 0:
                        print(f"  [retry] Attempt {retry + 1}/{MAX_RETRIES}...")
                        page.wait_for_timeout(2000)

                    try:
                        # ── Step 0: 确保 IDLE ──
                        ensure_idle(page)

                        # ── Step 1: 选币种 ──
                        if not select_currency(page, currency):
                            raise RuntimeError(
                                f"Currency {display} selection failed")

                        # ── Step 2: 设金额 ──
                        if not enter_amount(page, amount):
                            raise RuntimeError(
                                f"Amount {amount} setting failed")

                        # ── Step 3: 选时长 ──
                        if not select_duration(page, duration):
                            raise RuntimeError(
                                f"Duration {duration}s selection failed")

                        # ── Step 4: 下单 ──
                        trade_start = click_direction(page, direction)
                        if not trade_start:
                            raise RuntimeError("Order placement failed")

                        # ── Step 5: 等待结算 ──
                        result = wait_for_result(page, duration, r, trade_start)
                        results.append(result)
                        last_err = None
                        break  # success
                    except RuntimeError as e:
                        last_err = e
                        print(f"  [retry] Step failed: {e}")
                        continue

                if last_err:
                    raise last_err

                print(f"=== Round {r} complete ===")

                if r < rounds:
                    ensure_idle(page)
                    page.wait_for_timeout(1000)

            # ── Summary ──
            print(f"\n{'='*40}")
            wins = sum(1 for r in results if r.get("won"))
            losses = len(results) - wins
            for i, r in enumerate(results):
                tag = "W" if r.get("won") else "L"
                print(f"  Round {i+1}: {tag} | {r.get('texts', '')}")
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
            ctx.close()
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OKXOption Mobile Trade")
    parser.add_argument("--currency", default=TRADE_DEFAULTS["currency"])
    parser.add_argument("--amount", default=TRADE_DEFAULTS["amount"])
    parser.add_argument("--duration", default=TRADE_DEFAULTS["duration"])
    parser.add_argument("--direction", default=TRADE_DEFAULTS["direction"])
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()
    run(args.currency, args.amount, args.duration, args.direction, args.rounds)
