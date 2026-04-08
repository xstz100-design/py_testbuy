# BPTrading Instance 3 Configuration
# Each instance needs its own ACCOUNT, PASSWORD, and TELEGRAM_BOT_TOKEN

ACCOUNT = "33334444"
PASSWORD = "123456"
BASE_URL = "https://bptradinguk.com"
TRADE_URL = "https://bptradinguk.com/#/trade"

SPEED_MODE = "fast"

BROWSER = {
    "headless": True,
    "slow_mo": 0 if SPEED_MODE == "fast" else 80,
    "viewport": {"width": 1440, "height": 900},
}
TIMEOUT = {
    "navigation": 20000 if SPEED_MODE == "fast" else 45000,
    "element": 10000 if SPEED_MODE == "fast" else 20000,
}
DELAYS = {
    "page_load": 1500 if SPEED_MODE == "fast" else 3000,
    "dropdown_scroll": 100 if SPEED_MODE == "fast" else 200,
    "spa_switch": 500 if SPEED_MODE == "fast" else 1000,
    "input_verify": 200 if SPEED_MODE == "fast" else 400,
    "popup_check": 300 if SPEED_MODE == "fast" else 600,
}
STABILITY = {
    "log_max_bytes": 10 * 1024 * 1024,
    "log_backup_count": 5,
    "browser_restart_interval": 20,
    "network_retry_count": 3,
    "network_retry_delay": 5,
    "heartbeat_interval": 300,
    "memory_warning_mb": 1024,
    "screenshot_retention_days": 1,
}

TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_3"
TELEGRAM_ALLOWED_CHAT_IDS = []

TRADE_DEFAULTS = {
    "currency": "BTC",
    "amount": 100,
    "duration": 60,
    "direction": "up",
}

CURRENCY_CATEGORIES = {
    "BTC": "crypto", "ETH": "crypto", "LTC": "crypto", "LINK": "crypto",
    "DOGE": "crypto", "BNB": "crypto", "SOL": "crypto", "XRP": "crypto",
    "ADA": "crypto", "DOT": "crypto", "MATIC": "crypto", "SHIB": "crypto",
    "AVAX": "crypto", "TRX": "crypto", "UNI": "crypto", "ATOM": "crypto",
    "XLM": "crypto", "ETC": "crypto", "FIL": "crypto", "NEAR": "crypto",
    "APT": "crypto",
    "GOLD": "commodity", "SILVER": "commodity",
    "CRUDE OIL": "commodity", "BRENT OIL": "commodity",
    "EUR/USD": "forex", "USD/CAD": "forex", "GBP/USD": "forex",
    "EUR/JPY": "forex", "USD/JPY": "forex", "AUD/USD": "forex",
    "NZD/USD": "forex", "USD/CHF": "forex", "GBP/JPY": "forex",
    "EUR/GBP": "forex", "AUD/JPY": "forex", "CAD/JPY": "forex",
}

def get_display(currency):
    return currency

def get_category(currency):
    return CURRENCY_CATEGORIES.get(currency.upper(), "crypto")
