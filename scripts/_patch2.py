"""Patch mobile/trader.py: replace _get_balance/_parse_result_strict/wait_for_result
with countdown-disappear based settlement detection."""

path = "c:/Users/Administrator/Desktop/okxoption-trading/scripts/mobile/trader.py"
lines = open(path, encoding="utf-8").readlines()

# --- find the start/end lines ---
start_line = None
end_line = None
for i, l in enumerate(lines):
    if start_line is None and "_get_balance" in l and "def _get_balance" in l:
        # also capture the section header above it
        start_line = i - 3  # includes the === section header
    if end_line is None and i > 10 and "def run(" in l:
        end_line = i
        break

print(f"Replacing lines {start_line+1} to {end_line} (1-based)")

NEW_CODE = r'''# ═══════════════════════════════════════
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
    dur_sec = int(duration)
    expiry_at = trade_start + dur_sec
    print(f"  [wait] Waiting up to {dur_sec + 25}s for settlement...")

    initial_balance = _read_balance(page)
    if initial_balance:
        print(f"  [balance] Before: ${initial_balance:,.2f}")

    result = {"won": False, "profit": "", "texts": ""}
    best_shot = None

    # Phase 1: wait quietly until 2s before expiry
    quiet_until = expiry_at - 2.0
    while time.time() < quiet_until:
        remaining = quiet_until - time.time()
        time.sleep(min(0.4, max(0, remaining)))

    # Phase 2: wait for the countdown to disappear (= trade settled)
    print("  [burst] Waiting for settlement countdown to end...")
    scan_end = time.time() + 30   # up to 30s past quiet_until

    countdown_seen = True   # we know trade is active right now
    settled = False

    while time.time() < scan_end:
        visible = _is_countdown_visible(page)

        if countdown_seen and not visible:
            # Countdown just disappeared -> trade settled!
            settled = True
            print("  [burst] Settlement detected (countdown gone)")
            if not best_shot:
                best_shot = shot(page, f"trade-result-r{r}")

            # Wait up to 3s for balance to update
            for _ in range(15):
                time.sleep(0.2)
                final_balance = _read_balance(page)
                if final_balance and initial_balance and abs(final_balance - initial_balance) > 0.1:
                    break
            else:
                final_balance = _read_balance(page)

            if final_balance:
                print(f"  [balance] After:  ${final_balance:,.2f}")

            # Popup text from JS observer (may be caught if popup was fast)
            js_info = page.evaluate(
                """() => ({text: window.__settlementText||'',
                           html: window.__settlementHTML||''})"""
            )
            popup_text = js_info.get("text", "")

            parsed = _parse_win_loss(initial_balance, final_balance or 0, popup_text)
            result.update(parsed)
            result["texts"] = popup_text or f"balance: {initial_balance}->{final_balance}"

            status = "Won" if result["won"] else "Lost"
            print(f"  [result] {status} | Profit: {result.get('profit', '0')}")

            _close_result_popup(page)
            print("  [result] Popup closed")
            page.wait_for_timeout(700)
            if get_page_state(page) != "idle":
                _close_result_popup(page)
                page.wait_for_timeout(700)
            return result

        if visible:
            countdown_seen = True
        time.sleep(0.15)

    # Timeout fallback
    page.evaluate("() => { if(window.__settlementTimer) clearInterval(window.__settlementTimer); }")
    final_balance = _read_balance(page)
    if final_balance and initial_balance and abs(final_balance - initial_balance) > 0.1:
        if not best_shot:
            shot(page, f"trade-result-r{r}")
        parsed = _parse_win_loss(initial_balance, final_balance, "")
        result.update(parsed)
        status = "Won" if result["won"] else "Lost"
        print(f"  [result] {status} (balance fallback) | {initial_balance} -> {final_balance}")
    else:
        page_state = get_page_state(page)
        if not best_shot:
            label = "auto-settled" if page_state == "idle" else "timeout"
            shot(page, f"{label}-r{r}")
        print("  [warn] Settlement result undetermined")
    return result


'''

new_lines = lines[:start_line] + [NEW_CODE] + lines[end_line:]
open(path, "w", encoding="utf-8").writelines(new_lines)
print("Patch applied.")
