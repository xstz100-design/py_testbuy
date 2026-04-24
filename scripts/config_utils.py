# BPTrading Config Utilities
# Non-sensitive currency data, trade defaults, and normalization helpers.
# This file is tracked by git and safe to share across machines.
# Sensitive credentials (ACCOUNT, PASSWORD, tokens) live in config.py (gitignored).

TRADE_DEFAULTS = {
    "currency": "BTC",
    "amount": 100,
    "duration": 60,
    "direction": "up",
}

CURRENCY_CATEGORIES = {
    # Crypto (available on BPTrading site)
    "BTC": "crypto",
    "ETH": "crypto",
    "LTC": "crypto",
    "DOGE": "crypto",
    "LINK": "crypto",
    "BNB": "crypto",
    # Commodity
    "GOLD": "commodity",
    "SILVER": "commodity",
    "CRUDE OIL": "commodity",
    "BRENT OIL": "commodity",
    # Forex
    "EUR/USD": "forex",
    "USD/CAD": "forex",
    "GBP/USD": "forex",
    "EUR/JPY": "forex",
    "USD/JPY": "forex",
    "EUR/AUD": "forex",
    "GBP/CAD": "forex",
    "AUD/USD": "forex",
    # Index (futures)
    "ES": "index",
    "NQ": "index",
    "YM": "index",
}

# Exact display names as shown in BPTrading dropdown
# Only entries that differ from the uppercase canonical key are listed here
DISPLAY_NAMES: dict[str, str] = {
    "CRUDE OIL": "Crude Oil",
    "BRENT OIL": "Brent Oil",
    "GOLD":      "Gold",
    "SILVER":    "Silver",
}


def get_display(currency: str) -> str:
    """Return the exact display name as shown on BPTrading dropdown."""
    upper = currency.strip().upper()
    return DISPLAY_NAMES.get(upper, upper)


def get_category(currency: str) -> str:
    return CURRENCY_CATEGORIES.get(currency.strip().upper(), "crypto")


# Aliases for common typos / case variations → canonical name
# Keys must be lowercase for case-insensitive matching
CURRENCY_ALIASES: dict[str, str] = {
    # Crude Oil (WTI)
    "crude oil":   "CRUDE OIL",
    "crudeoil":    "CRUDE OIL",
    "crude_oil":   "CRUDE OIL",
    "crude-oil":   "CRUDE OIL",
    "crude":       "CRUDE OIL",
    "wti":         "CRUDE OIL",
    "oil":         "CRUDE OIL",
    "usoil":       "CRUDE OIL",
    "us oil":      "CRUDE OIL",
    "wti oil":     "CRUDE OIL",
    # Brent Oil
    "brent oil":   "BRENT OIL",
    "brentoil":    "BRENT OIL",
    "brent_oil":   "BRENT OIL",
    "brent-oil":   "BRENT OIL",
    "brent":       "BRENT OIL",
    "ukoil":       "BRENT OIL",
    "uk oil":      "BRENT OIL",
    "brent crude": "BRENT OIL",
    # Gold
    "gold":        "GOLD",
    "xau":         "GOLD",
    "xauusd":      "GOLD",
    "xau/usd":     "GOLD",
    # Silver
    "silver":      "SILVER",
    "xag":         "SILVER",
    "xagusd":      "SILVER",
    "xag/usd":     "SILVER",
    # Index futures
    "es":          "ES",
    "s&p":         "ES",
    "sp500":       "ES",
    "s&p500":      "ES",
    "nq":          "NQ",
    "nasdaq":      "NQ",
    "nasdaq100":   "NQ",
    "ym":          "YM",
    "dow":         "YM",
    "dow jones":   "YM",
    # Forex aliases
    "eurusd":      "EUR/USD",
    "usdcad":      "USD/CAD",
    "gbpusd":      "GBP/USD",
    "eurjpy":      "EUR/JPY",
    "usdjpy":      "USD/JPY",
    "euraud":      "EUR/AUD",
    "gbpcad":      "GBP/CAD",
    "audusd":      "AUD/USD",
}


def normalize_currency(currency: str) -> str:
    """Normalize user input to the canonical currency name.
    Handles common typos, abbreviations, case variations, and near-typos via fuzzy matching."""
    import difflib
    key = currency.strip().lower()

    # 1. Exact alias match
    if key in CURRENCY_ALIASES:
        return CURRENCY_ALIASES[key]

    # 2. Exact canonical match (e.g. "BTC", "ETH")
    upper = currency.strip().upper()
    if upper in CURRENCY_CATEGORIES:
        return upper

    # 3. Fuzzy match against all known canonical names
    all_canonical = list(CURRENCY_CATEGORIES.keys())
    candidates = {v for v in CURRENCY_ALIASES.values()} | set(all_canonical)
    matches = difflib.get_close_matches(upper, candidates, n=1, cutoff=0.6)
    if matches:
        print(f"[normalize] Fuzzy matched '{currency}' -> '{matches[0]}'")
        return matches[0]

    # 4. Fallback: return uppercased as-is
    return upper
