# BPTrading Automated Trading Bot

Python + Playwright automated trading system for BPTrading (bptradinguk.com) with Telegram integration.

## Features

- Desktop and mobile browser automation (Chromium)
- Telegram bot control (queue, batch orders, stop, restart)
- Auto-restart on crash with watchdog
- Log rotation and screenshot cleanup

## Setup

1. Install dependencies:
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install playwright psutil
playwright install chromium
```

2. Configure:
```bash
cp scripts/config.example.py scripts/config.py
# Edit config.py with your credentials
```

3. Run:
```bash
python scripts/telegram_bot.py
# Or use watchdog for auto-restart:
python scripts/bot_watchdog.py
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/health` | System status |
| `/queue` | View queue |
| `/clear` | Clear queue |
| `/stop` | Stop current task |
| `/restart` | Restart bot |

## Order Format

```
BTC 60 up 60s
ETH 100 down 90s mobile
BTC 60 up 60s, ETH 50 down 120s  # batch
```

Valid durations: 60s, 90s, 120s, 180s, 300s

## License

Private use only.
