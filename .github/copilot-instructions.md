This is an OKXOption automated trading project using Python + Playwright (Chromium).

Key facts:
- Trading scripts are in `scripts/` (trade.py, batch_trade.py, config.py)
- Desktop automation: `scripts/desktop/trader.py` (1440x900 Chromium)
- Mobile automation: `scripts/mobile/trader.py` (iPhone emulation 430x932)
- Screenshots are saved to `scripts/screenshots/`
- When the user sends a message matching `{CURRENCY} {AMOUNT} {DIRECTION} {DURATION}`, invoke the `okxoption-trading` skill to execute the trade automatically.
- All code and documentation is in English.

CRITICAL — After running any trade command:
1. You MUST parse the result from the script output (between ===RESULT=== and ===END=== markers).
2. You MUST reply to the user with the trade result.
3. You MUST send the latest screenshot from `scripts/screenshots/`.
4. NEVER stay silent after a trade command finishes. The user is waiting for feedback.
