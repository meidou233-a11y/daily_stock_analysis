from types import SimpleNamespace

import pytest

from scripts import check_daily_trading_day as daily


@pytest.mark.parametrize("mode,stocks,region,open_markets,force,disabled,expected", [
    ("full", ["600519", "AAPL"], "both", [], False, False, True),
    ("full", ["600519", "AAPL"], "cn", ["us"], False, False, False),
    ("market-only", ["AAPL"], "cn", ["us"], False, False, True),
    ("market-only", ["600519"], "us", ["us"], False, False, False),
    ("stocks-only", ["600519"], "us", ["us"], False, False, True),
    ("full", ["600519"], "cn", [], True, False, False),
    ("full", ["600519"], "cn", [], False, True, False),
])
def test_actions_preflight_uses_real_cli_filter(
    monkeypatch, mode, stocks, region, open_markets, force, disabled, expected
):
    from src.core import trading_calendar

    monkeypatch.setattr(trading_calendar, "get_open_markets_today", lambda: open_markets)
    config = SimpleNamespace(
        stock_list=stocks,
        market_review_enabled=True,
        market_review_region=region,
        trading_day_check_enabled=not disabled,
    )
    assert daily.should_skip(config, mode, force) == expected


def test_explicit_market_review_overrides_disabled_config_without_mutation(monkeypatch):
    from src.core import trading_calendar

    monkeypatch.setattr(trading_calendar, "get_open_markets_today", lambda: {"us"})
    config = SimpleNamespace(
        stock_list=["600519"], market_review_enabled=False,
        market_review_region="us", trading_day_check_enabled=True,
    )
    assert not daily.should_skip(config, "market-only")
    assert config.market_review_enabled is False


def test_empty_watchlist_reaches_main_validation():
    config = SimpleNamespace(stock_list=[], market_review_enabled=False)
    assert not daily.should_skip(config, "full")
