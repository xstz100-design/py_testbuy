# Mac Deployment Guide

## One-Click Deploy

```bash
# 1. Clone the project
git clone https://github.com/xstz100-design/py_testbuy.git BPtrading
cd BPtrading

# 2. Run deploy script (installs Python venv, dependencies, Chromium)
bash scripts/deploy_mac.sh

# 3. Edit config with your credentials
nano scripts/config.py
# Set: ACCOUNT, PASSWORD, TELEGRAM_BOT_TOKEN

# 4. Start the bot
bash scripts/start_bot_mac.sh
```

## Commands

| Command | Description |
|---------|-------------|
| `bash scripts/deploy_mac.sh` | Install everything |
| `bash scripts/start_bot_mac.sh` | Start bot (background) |
| `bash scripts/stop_bot_mac.sh` | Stop bot |
| `tail -f scripts/watchdog.log` | View live logs |

## Prerequisites

- macOS 12+ (Monterey or later)
- Python 3.10+ (`brew install python3` if needed)
- ~500MB disk space (Chromium browser)

## Troubleshooting

**Playwright browser fails to launch:**
```bash
# Install system dependencies
.venv/bin/python3 -m playwright install-deps chromium
```

**Permission denied on scripts:**
```bash
chmod +x scripts/*.sh
```

**Bot crashes on start:**
```bash
# Check logs
tail -100 scripts/watchdog.log

# Test manually
.venv/bin/python3 scripts/telegram_bot.py
```

**Reset session (if login fails):**
```bash
echo '{"cookies": [], "origins": []}' > scripts/auth.json
```
