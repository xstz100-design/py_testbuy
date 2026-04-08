"""BPTrading Trade - Unified Entry Point.

Runs a single trade on either desktop or mobile.

Usage:
    python trade.py --mode desktop --currency BTC --amount 60 --direction down --duration 60
    python trade.py --mode mobile --currency ETH --amount 100 --direction up --duration 120
    python trade.py --currency LTC --amount 30 --direction down
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import TRADE_DEFAULTS


def main():
    parser = argparse.ArgumentParser(description="BPTrading Trade")
    parser.add_argument("--mode", choices=["desktop", "mobile"], default="desktop",
                        help="desktop or mobile")
    parser.add_argument("--currency", default=TRADE_DEFAULTS["currency"])
    parser.add_argument("--amount", default=TRADE_DEFAULTS["amount"])
    parser.add_argument("--duration", default=TRADE_DEFAULTS["duration"])
    parser.add_argument("--direction", default=TRADE_DEFAULTS["direction"])
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--account", default=None, help="Override account")
    parser.add_argument("--password", default=None, help="Override password")
    args = parser.parse_args()

    # Normalize direction to lowercase
    direction = args.direction.lower()
    if direction not in {"up", "down"}:
        print(f"Invalid direction: {args.direction}. Must be 'up' or 'down'.")
        sys.exit(1)

    # Override config account/password if provided
    if args.account is not None:
        import config as _cfg
        _cfg.ACCOUNT = args.account
    if args.password is not None:
        import config as _cfg
        _cfg.PASSWORD = args.password

    if args.mode == "desktop":
        from desktop.trader import run
    else:
        from mobile.trader import run

    run(args.currency, args.amount, args.duration, direction, args.rounds)


if __name__ == "__main__":
    main()
