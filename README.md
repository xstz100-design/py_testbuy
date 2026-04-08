# BPTrading Automated Trading Bot

Python + Playwright automated trading system for [bptradinguk.com](https://bptradinguk.com/) with Telegram bot integration.

## Architecture

**Multi-user concurrent mode**: One bot serves multiple users simultaneously.
- Each user (chat_id) gets an independent task queue and worker thread
- User A's trade executes in parallel with User B's — no blocking
- Screenshots are isolated per user (`screenshots/{chat_id}/`) to prevent cross-talk
- Settings, accounts, and withdrawal configs are stored per-user

## Project Structure

```
BPtrading/
├── scripts/
│   ├── config.example.py      # Config template (copy to config.py)
│   ├── config.py               # Your credentials (git-ignored)
│   ├── telegram_bot.py         # Telegram bot (long-polling, queue, commands)
│   ├── trade.py                # Trade entry point (desktop/mobile)
│   ├── batch_trade.py          # Batch trade logic & result parsing
│   ├── withdraw.py             # Withdrawal automation
│   ├── bot_watchdog.py         # Auto-restart watchdog
│   ├── maintenance.py          # Screenshot/log cleanup
│   ├── desktop/
│   │   └── trader.py           # Desktop Chromium automation (1440x900)
│   ├── mobile/
│   │   └── trader.py           # Mobile iPhone emulation (430x932)
│   ├── instances/              # Multi-instance configs (3 bots parallel)
│   │   ├── instance1/config.py
│   │   ├── instance2/config.py
│   │   └── instance3/config.py
│   ├── deploy_mac.sh           # Mac one-click deploy
│   ├── start_bot_mac.sh        # Start single bot (Mac)
│   ├── stop_bot_mac.sh         # Stop single bot (Mac)
│   ├── multi_start_mac.sh      # Start all instances (Mac)
│   ├── multi_stop_mac.sh       # Stop all instances (Mac)
│   ├── multi_status_mac.sh     # Check instance status (Mac)
│   ├── start_bot.bat           # Start bot (Windows)
│   └── start_bot_hidden.vbs    # Start bot hidden (Windows)
├── docs/
│   └── MAC_DEPLOY.md           # Mac deployment guide
├── requirements.txt
└── README.md
```

## Quick Start

### Windows
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp scripts/config.example.py scripts/config.py
# Edit scripts/config.py with your credentials
python scripts/bot_watchdog.py
```

### Mac (One-Click)
```bash
git clone https://github.com/xstz100-design/py_testbuy.git BPtrading
bash BPtrading/scripts/deploy_mac.sh
bash BPtrading/scripts/start_bot_mac.sh
```

### Multi-Instance (3 Bots Parallel)
```bash
# Edit each instance config with different Bot Token & account
nano scripts/instances/instance1/config.py
nano scripts/instances/instance2/config.py
nano scripts/instances/instance3/config.py

bash scripts/multi_start_mac.sh      # Start all
bash scripts/multi_status_mac.sh     # Check status
bash scripts/multi_stop_mac.sh       # Stop all
```

## Telegram Commands

### Trading
```
BTC 60 up 60s                        # Single order
ETH 100 down 90s mobile              # Specify mode
BTC 60 up 60s, ETH 50 down 120s      # Batch order
```
Valid durations: 60s, 90s, 120s, 180s, 300s

### Settings
| Command | Description |
|---------|-------------|
| `mode=mobile` / `mode=desktop` | Switch trading mode |
| `delay=5` | Pause 5s between trades |

### Account Management
| Command | Description |
|---------|-------------|
| `add=ACCOUNT,pass=PASSWORD` | Add account |
| `del=ACCOUNT` | Delete account |
| `acc=ACCOUNT` | Switch active account |
| `/accounts` | List all accounts |

### Withdrawal
| Command | Description |
|---------|-------------|
| `erc20=ADDRESS` | Set ERC20 wallet address |
| `wdmethod=usdt` / `wdmethod=bank` | Set withdrawal method |
| `wd=AMOUNT` | Execute withdrawal |

### Management
| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/health` | System status |
| `/settings` | Current settings |
| `/queue` | View task queue |
| `/clear` | Clear queue |
| `/cancel N` | Cancel task N |
| `/stop` | Stop current task |
| `/restart` | Restart bot |

## Supported Currencies

**Crypto:** BTC, ETH, LTC, LINK, DOGE, BNB, SOL, XRP, ADA, DOT, MATIC, SHIB, AVAX, TRX, UNI, ATOM, XLM, ETC, FIL, NEAR, APT

**Commodity:** GOLD, SILVER, CRUDE OIL, BRENT OIL

**Forex:** EUR/USD, USD/CAD, GBP/USD, EUR/JPY, USD/JPY, AUD/USD, NZD/USD, USD/CHF, GBP/JPY, EUR/GBP, AUD/JPY, CAD/JPY

## License

Private use only.
