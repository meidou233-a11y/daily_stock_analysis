"""Build a disposable daily pool using the bundled screening filters and scores."""
from dataclasses import replace
import re

import pandas as pd

from src.services.screening.config import Config
from src.services.screening.daily import enrich_daily_features
from src.services.screening.filter import apply_hard_filters, without_daily_filters, requires_daily_features
from src.services.screening.scorer import compute_screen_scores
from src.services.screening.snapshot import fetch_snapshot_with_fallback
from src.services.screening.snapshot_us import fetch_us_snapshot, fetch_us_universe, fetch_daily_history_yfinance
from src.services.screening.strategy import load_all_strategies
from src.services.stock_list_parser import split_stock_list


def canonical_code(value, market):
    value = str(value).strip()
    if market == "hk":
        match = re.fullmatch(r"(?:hk)?(\d{1,5})(?:\.HK)?", value, re.I)
        return "hk" + match.group(1).zfill(5) if match else ""
    if market == "cn":
        return value.zfill(6) if value.isdigit() and len(value) <= 6 else ""
    return value.upper() if re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,19}", value) else ""


def merge_daily_pool(base, extra, candidates, limit=5):
    """Preserve fixed entries and round-robin markets; never persist candidates."""
    fixed, seen = [], set()
    for code in split_stock_list(base) + split_stock_list(extra):
        if code.upper() not in seen:
            fixed.append(code)
            seen.add(code.upper())
    groups = {}
    for market, rows in candidates.items():
        groups[market] = []
        for row in rows:
            code = canonical_code(row.get("code", ""), market)
            if code and code.upper() not in seen:
                groups[market].append({**row, "code": code, "market": market})
    added = []
    while len(added) < limit and any(groups.values()):
        for rows in groups.values():
            while rows:
                row = rows.pop(0)
                if row["code"].upper() not in seen:
                    seen.add(row["code"].upper())
                    added.append(row)
                    break
            if len(added) >= limit:
                break
    return fixed + [row["code"] for row in added], added


def fetch_market_snapshot(market, config, universe_limit):
    if market == "cn":
        return fetch_snapshot_with_fallback(config.snapshot_source_priority, market="cn")
    if market == "us":
        # The existing adapter supports an explicit configurable universe.
        import os
        tickers = fetch_us_universe(os.getenv("AUTO_SCREEN_US_UNIVERSE", "default"))
        return fetch_us_snapshot(tickers=tickers[:universe_limit])
    if market != "hk":
        raise ValueError("Unsupported auto screening market")
    import akshare as ak
    spot = ak.stock_hk_spot_em()
    ranked = spot.assign(_amount=pd.to_numeric(spot["成交额"], errors="coerce"))
    codes = ranked.sort_values("_amount", ascending=False)["代码"].head(universe_limit)
    tickers = [str(int(code)).zfill(4) + ".HK" for code in codes if str(code).isdigit()]
    if not tickers:
        raise ValueError("Empty Hong Kong universe")
    return fetch_us_snapshot(tickers=tickers)


def screen_snapshot(snapshot, market, profiles, daily_limit=20, history_fetcher=None):
    """Union enabled strategy results; missing required data never counts as a match."""
    strategies = load_all_strategies(Config.from_env().strategies_dir)
    winners = {}
    warnings = []
    for strategy_name, overrides in profiles.items():
        try:
            strategy = strategies[strategy_name]
            filters = replace(strategy.screening.hard_filters, **overrides)
            pool = apply_hard_filters(snapshot, without_daily_filters(filters))
            pool = pool.sort_values("amount", ascending=False).head(daily_limit)
            if pool.empty:
                continue
            if requires_daily_features(filters):
                pool = enrich_daily_features(pool, max_rows=daily_limit, history_fetcher=history_fetcher)
            pool = apply_hard_filters(pool, filters)
            ranked = compute_screen_scores(pool, strategy.screening)
            for _, row in ranked.iterrows():
                code = canonical_code(row["code"], market)
                if not code:
                    continue
                score = float(row["screen_score"])
                if not pd.notna(score):
                    continue
                previous = winners.get(code)
                matches = list(previous["strategies"]) if previous else []
                if strategy_name not in matches:
                    matches.append(strategy_name)
                if previous is None or score > previous["score"]:
                    winners[code] = {"code": code, "name": str(row.get("name", code)), "score": score,
                                     "strategies": matches}
                else:
                    previous["strategies"] = matches
        except Exception as exc:
            warnings.append(f"{market}/{strategy_name}: {type(exc).__name__}")
    return sorted(winners.values(), key=lambda row: (-row["score"], row["code"])), warnings


def foreign_history(code, **kwargs):
    return fetch_daily_history_yfinance(code, lookback_days=kwargs.get("lookback_days", 120))
