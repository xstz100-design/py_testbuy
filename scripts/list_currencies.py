"""list_currencies.py — 打开 BPTrading 页面，把下拉框里所有可交易货币全部列出来。

用法:
    python scripts/list_currencies.py
"""
import sys
import re
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TRADE_URL, ACCOUNT, PASSWORD, TIMEOUT, DELAYS
from playwright.sync_api import sync_playwright

AUTH_FILE = Path(__file__).resolve().parent / "auth.json"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context_kwargs = {"viewport": {"width": 1440, "height": 900}}
        if AUTH_FILE.exists():
            context_kwargs["storage_state"] = str(AUTH_FILE)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        # ── 登录 ──
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
            page.wait_for_timeout(2500)
            context.storage_state(path=str(AUTH_FILE))
        else:
            print("[login] Session valid")

        # ── 等待页面就绪 ──
        try:
            page.get_by_role("button", name=re.compile(r"up|down", re.I)).first.wait_for(
                state="visible", timeout=8000
            )
        except Exception:
            page.wait_for_timeout(2000)

        # ── 打开货币下拉框 ──
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        page.locator(".ant-select").first.click()
        page.wait_for_timeout(600)

        # ── 滚动收集所有选项 ──
        currencies = []
        seen = set()
        no_new_count = 0

        def collect_visible():
            added = 0
            for sel in [
                ".ant-select-item-option-content",
                ".ant-select-item[title]",
                ".ant-select-item-option",
            ]:
                for item in page.locator(sel).all():
                    try:
                        text = (item.get_attribute("title") or item.text_content() or "").strip()
                        if text and text not in seen:
                            seen.add(text)
                            currencies.append(text)
                            added += 1
                    except Exception:
                        pass
            return added

        for i in range(80):
            before = len(currencies)
            collect_visible()
            after = len(currencies)

            # 尝试多种滚动方式
            page.evaluate(r"""() => {
                const targets = [
                    document.querySelector('.rc-virtual-list-holder'),
                    document.querySelector('.ant-select-dropdown .rc-virtual-list-holder-inner'),
                    document.querySelector('.ant-select-dropdown'),
                    document.querySelector('.ant-select-dropdown .ant-select-item:last-child'),
                ];
                for (const t of targets) {
                    if (t) {
                        t.scrollBy ? t.scrollBy({top: 200, behavior: 'instant'})
                                   : t.scrollIntoView && t.scrollIntoView({block: 'end'});
                        break;
                    }
                }
            }""")
            page.wait_for_timeout(200)

            if after == before:
                no_new_count += 1
                if no_new_count >= 5:
                    break
            else:
                no_new_count = 0

        # 最后再收集一次
        collect_visible()

        page.keyboard.press("Escape")
        browser.close()

        print(f"\n{'='*50}")
        print(f"共找到 {len(currencies)} 个可交易货币:")
        print('='*50)
        for idx, c in enumerate(currencies, 1):
            print(f"  {idx:3d}. {c}")
        print('='*50)

        # 输出 JSON 格式方便复制
        print("\n[JSON 格式]")
        print(json.dumps(currencies, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
