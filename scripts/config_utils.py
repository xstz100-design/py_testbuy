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
    "BTC":  "crypto",
    "ETH":  "crypto",
    "LTC":  "crypto",
    "DOGE": "crypto",
    "LINK": "crypto",
    "BNB":  "crypto",
    # Commodity
    "GOLD":      "commodity",
    "SILVER":    "commodity",
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
    "s&p 500":     "ES",
    "us500":       "ES",
    "spx":         "ES",
    "nq":          "NQ",
    "nasdaq":      "NQ",
    "nasdaq100":   "NQ",
    "nasdaq 100":  "NQ",
    "nas100":      "NQ",
    "us100":       "NQ",
    "ndx":         "NQ",
    "ym":          "YM",
    "dow":         "YM",
    "dow jones":   "YM",
    "dow30":       "YM",
    "us30":        "YM",
    "djia":        "YM",
    # Forex aliases
    "eurusd":      "EUR/USD",
    "eur usd":     "EUR/USD",
    "usdcad":      "USD/CAD",
    "usd cad":     "USD/CAD",
    "gbpusd":      "GBP/USD",
    "gbp usd":     "GBP/USD",
    "cable":       "GBP/USD",
    "eurjpy":      "EUR/JPY",
    "eur jpy":     "EUR/JPY",
    "usdjpy":      "USD/JPY",
    "usd jpy":     "USD/JPY",
    "euraud":      "EUR/AUD",
    "eur aud":     "EUR/AUD",
    "gbpcad":      "GBP/CAD",
    "gbp cad":     "GBP/CAD",
    "audusd":      "AUD/USD",
    "aud usd":     "AUD/USD",
    "aussie":      "AUD/USD",
    # Forex 2-letter trader shorthand (e.g. EU = EUR/USD)
    "eu":          "EUR/USD",
    "gu":          "GBP/USD",
    "uj":          "USD/JPY",
    "ej":          "EUR/JPY",
    "ea":          "EUR/AUD",
    "au":          "AUD/USD",
    "uc":          "USD/CAD",
    "gc":          "GBP/CAD",
    # Crypto aliases
    "bitcoin":     "BTC",
    "btcusd":      "BTC",
    "ethereum":    "ETH",
    "ethusd":      "ETH",
    "litecoin":    "LTC",
    "ltcusd":      "LTC",
    "dogecoin":    "DOGE",
    "dogeusd":     "DOGE",
    "chainlink":   "LINK",
    "linkusd":     "LINK",
    "binance":     "BNB",
    "bnbusd":      "BNB",
}


def normalize_currency(currency: str) -> str:
    """Normalize user input to the canonical currency name.
    Handles common typos, abbreviations, case variations, and near-typos via fuzzy matching."""
    import difflib, re
    key = currency.strip().lower()

    # 1. Exact alias match
    if key in CURRENCY_ALIASES:
        return CURRENCY_ALIASES[key]

    # 2. Exact canonical match (e.g. "BTC", "EUR/USD")
    upper = currency.strip().upper()
    if upper in CURRENCY_CATEGORIES:
        return upper

    # 2b. Normalize forex separator variants: EUR-USD / EUR.USD / EUR_USD / EUR\USD → EUR/USD
    #     Matches XxxXxx patterns like GBP-USD, eur.usd, AUD_USD, gbp\usd
    sep_norm = re.sub(
        r'^([A-Za-z]{2,4})\s*[-._\\]\s*([A-Za-z]{2,4})$',
        lambda m: f"{m.group(1).upper()}/{m.group(2).upper()}",
        currency.strip(),
    )
    if sep_norm != currency.strip():
        if sep_norm in CURRENCY_CATEGORIES:
            return sep_norm
        # Also try stripping slash to hit alias (e.g. "EURUSD")
        no_slash = sep_norm.lower().replace('/', '')
        if no_slash in CURRENCY_ALIASES:
            return CURRENCY_ALIASES[no_slash]

    # 3. Fuzzy match against all known canonical names
    all_canonical = list(CURRENCY_CATEGORIES.keys())
    candidates = {v for v in CURRENCY_ALIASES.values()} | set(all_canonical)
    matches = difflib.get_close_matches(upper, candidates, n=1, cutoff=0.6)
    if matches:
        print(f"[normalize] Fuzzy matched '{currency}' -> '{matches[0]}'")
        return matches[0]

    # 4. Fallback: return uppercased as-is
    return upper
