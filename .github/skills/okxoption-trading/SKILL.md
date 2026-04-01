---
name: okxoption-trading
description: "OKXOption automated trading skill. Use when the user sends trading instructions with asset, amount, direction, and duration. Supports both desktop and mobile execution, plus batch and scheduled orders."
argument-hint: "Single order: {currency} {amount} {direction up/down} {duration}s [mobile]. Batch order: one order per line. Example: BTC 60 down 60s mobile"
---

# OpenClaw - OKXOption Trading
description: "OKXOption automated trading skill. Use when the user sends trading instructions with asset, amount, direction, and duration. Supports desktop, mobile, batch, and scheduled execution, and always returns the latest screenshot."
argument-hint: "Single order: {currency} {amount} {direction} {duration}s [mobile]. Batch order: one order per line. Example: BTC 60 down 60s mobile"

---

## Mandatory Rules


Use this skill only for trade execution requests that match the order format below. Do not improvise browser actions when the scripts already cover the requested workflow.
### Rule 1: Parse Instructions

Parse every valid message using this format:

```text
{currency} {amount} {direction} {duration} [mode]
```

Parsing rules:
- Currency: BTC, LTC, ETH, DOGE, LINK, BNB, USD/CAD, EUR/USD, GOLD, and any other supported asset.
- Amount: numeric only, such as 60, 100, 500.
- Direction: up or down, case-insensitive.
- Duration: number followed by s, such as 60s, 120s, 300s. Extract the numeric part.
- Mode: if the message contains mobile, use mobile. Otherwise use desktop.

Examples:

| User message | Currency | Amount | Direction | Duration | Mode |
|---|---|---|---|---|---|
| BTC 60 down 60s | BTC | 60 | down | 60 | desktop |
| BTC 60 down 60s mobile | BTC | 60 | down | 60 | mobile |
| ETH 100 up 120s | ETH | 100 | up | 120 | desktop |
| LTC 30 down 60s mobile | LTC | 30 | down | 60 | mobile |
| GOLD 500 up 300s mobile | GOLD | 500 | up | 300 | mobile |

### Rule 2: Run Commands

After parsing, run the order immediately without asking for confirmation.

If the user sends multiple orders in one message, or sends many lines of orders at once, treat the message as a batch queue and run it through the batch runner instead of executing only the first line.

Execution priority:
- One valid order: run `trade.py` directly.
- Multiple orders in one message: write or reuse a batch file and run `batch_trade.py`.
- If the user explicitly asks for desktop or mobile, honor that mode.
- If mode is omitted, default to desktop.

Single order:

```bash
cd {baseDir}/scripts
python trade.py --mode {mode} --currency {currency} --amount {amount} --direction {direction} --duration {duration}
```

Batch or scheduled orders:

```bash
cd {baseDir}/scripts
python batch_trade.py --orders-file {file}
```

### Rule 3: Reply Format — MANDATORY

**You MUST reply to the user after the command finishes. This is not optional. Even if the output is long, you MUST parse the result and send a reply.**

The script output contains a result block between `===RESULT===` and `===END===` markers. Parse the JSON inside that block.

Do not infer the outcome from logs outside the result block. If the result block is missing or malformed, report that explicitly.

If `status` is `ok`:

```text
Trade completed ({mode})
Currency: {currency}
Amount: {amount}
Direction: {direction}
Duration: {duration}s
Result: {wins}W / {losses}L
```

If `status` is `error`:

```text
Trade failed ({mode})
Currency: {currency}
Error: {message from JSON}
```

### Rule 4: Send Screenshot — MANDATORY

**You MUST send the final screenshot after every trade. Never skip this step.**

After the command finishes, find the **most recently modified** `.png` file in `{baseDir}/scripts/screenshots/` and send it to the user along with the reply text.

If no screenshot exists, say so clearly and still provide the parsed trade result.

Recommended screenshot order:
- Use the newest file by modification time.
- Prefer the latest `trade-result-*` or `mobile-trade-result-*` file when multiple screenshots exist for the same run.

Filename patterns:
- Desktop: trade-result-{timestamp}.png, trade-timeout-{timestamp}.png, trade-error.png
- Mobile: mobile-trade-result-r{round}.png, mobile-timeout-r{round}.png, mobile-error.png

### Rule 5: Never Do These

- Do not ask for confirmation before running a valid order.
- Do not skip the reply after the command finishes.
- Do not skip the final screenshot when one exists.
- Do not send text only when a final screenshot exists.
- Do not control the browser manually outside the provided scripts.
- Do not remain silent after the script completes — always reply with the result.

---

## Environment Setup

```bash
pip install playwright
playwright install chromium
```

## Project Structure

```text
scripts/
├── trade.py
├── batch_trade.py
├── config.py
├── auth.json
├── screenshots/
├── desktop/
│   ├── __init__.py
│   └── trader.py
└── mobile/
    ├── __init__.py
    └── trader.py
```

## Commands

```bash
cd {baseDir}/scripts

# Desktop
python trade.py --mode desktop --currency BTC --amount 60 --direction down --duration 60

# Mobile
python trade.py --mode mobile --currency LTC --amount 30 --direction up --duration 60

# Repeat the same order
python trade.py --mode desktop --currency BTC --amount 100 --direction up --duration 60 --rounds 3

# Run multiple orders from a file
python batch_trade.py --orders-file orders.txt
```

## Batch Orders

Use one order per line:

```text
BTC 60 down 60s desktop
ETH 100 up 120s mobile
GOLD 70 down 60s at=2026-03-27T21:30:00 desktop
EUR/USD 65 up 60s delay=90 mobile
```

Optional fields:
- desktop or mobile
- delay={seconds}: wait this many seconds after the previous order finishes
- at={ISO datetime}: wait until the specified local time before starting the order

Execution rules:
- Orders run strictly one by one.
- A new order starts only after the previous order has fully finished.
- If both delay and at are present, the runner waits for whichever is later.
- This is the correct way to process many orders listed in one user message.

## Supported Assets

| Category | Assets |
|---|---|
| Crypto | BTC, LTC, ETH, DOGE, LINK, BNB |
| Forex | USD/CAD, EUR/USD, GBP/USD, EUR/JPY, USD/JPY, EUR/AUD, GBP/CAD, AUD/USD |
| Commodities | GOLD, SILVER, CRUDE OIL, BRENT OIL, NATURAL GAS |
| Indices | ES, NQ, YM |

## Supported Durations

60s, 90s, 120s, 180s, 300s

## Output Format

Success:

```json
{"status": "ok", "rounds": 1, "wins": 0, "losses": 1, "screenshots": "/absolute/path/to/scripts/screenshots/latest.png"}
```

Failure:

```json
{"status": "error", "message": "error details"}
```
