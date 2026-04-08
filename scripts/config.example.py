# BPTrading Configuration
# Copy this file to config.py and fill in your credentials

ACCOUNT = "your_account"
PASSWORD = "your_password"
BASE_URL = "https://bptradinguk.com"
TRADE_URL = "https://bptradinguk.com/#/trade"

# Speed mode: "fast" = minimum delays, "normal" = safer delays
SPEED_MODE = "fast"

BROWSER = {
    "headless": True,
    "slow_mo": 0 if SPEED_MODE == "fast" else 80,
    "viewport": {"width": 1440, "height": 900},
}
TIMEOUT = {
    "navigation": 45000 if SPEED_MODE == "fast" else 60000,
    "element": 20000 if SPEED_MODE == "fast" else 30000,
}

# Delays in milliseconds (configurable per speed mode)
DELAYS = {
    "page_load": 1500 if SPEED_MODE == "fast" else 3000,
    "dropdown_scroll": 100 if SPEED_MODE == "fast" else 250,
    "spa_switch": 600 if SPEED_MODE == "fast" else 1200,
    "input_verify": 200 if SPEED_MODE == "fast" else 400,
    "popup_check": 300 if SPEED_MODE == "fast" else 700,
}

# Long-term stability config
STABILITY = {
    "log_max_bytes": 10 * 1024 * 1024,
    "log_backup_count": 5,
    "browser_restart_interval": 20,
    "network_retry_count": 3,
    "network_retry_delay": 5,
    "heartbeat_interval": 300,
    "memory_warning_mb": 1024,
    "screenshot_retention_days": 3,
}

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = "your_telegram_bot_token"
TELEGRAM_ALLOWED_CHAT_IDS = []  # Empty = allow all; add chat IDs to whitelist

TRADE_DEFAULTS = {
    "currency": "BTC",
    "amount": 100,
    "duration": 60,
    "direction": "up",
}

CURRENCY_CATEGORIES = {
    "BTC": "crypto",
    "ETH": "crypto",
    "LTC": "crypto",
    "LINK": "crypto",
    "DOGE": "crypto",
    "BNB": "crypto",
    "GOLD": "commodity",
    "EUR/USD": "forex",
    "USD/CAD": "forex",
    "GBP/USD": "forex",
    "EUR/JPY": "forex",
}
