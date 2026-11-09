"""Apply the CLI trading-day filter before the Actions analysis/send pair."""
import argparse
from copy import copy
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def should_skip(config, mode, force_run=False):
    from main import _compute_trading_day_filter

    if mode != "market-only" and not config.stock_list:
        # Let the main entry validate an empty watchlist instead of masking it.
        return False
    if mode == "market-only":
        # Explicit CLI market-review mode overrides MARKET_REVIEW_ENABLED.
        config = copy(config)
        config.market_review_enabled = True
    args = SimpleNamespace(force_run=force_run, no_market_review=mode == "stocks-only")
    codes = [] if mode == "market-only" else config.stock_list
    return _compute_trading_day_filter(config, args, codes)[2]


def main():
    from src.config import get_config

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("full", "stocks-only", "market-only"), required=True)
    parser.add_argument("--force-run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    skip = should_skip(get_config(), args.mode, args.force_run)
    args.output.write_text("true" if skip else "false", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
