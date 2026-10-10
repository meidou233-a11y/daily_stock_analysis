"""Regression coverage for market-review gaps, dates and Southbound units."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider.akshare_fetcher import AkshareFetcher
from data_provider.efinance_fetcher import EfinanceFetcher
from src.core.market_profile import get_profile
from src.core.market_strategy import get_market_strategy_blueprint
from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview


def _analyzer(region="cn"):
    ma = MarketAnalyzer.__new__(MarketAnalyzer)
    ma.region = region
    ma.profile = get_profile(region)
    ma.strategy = get_market_strategy_blueprint(region)
    ma.config = SimpleNamespace(report_language="zh")
    return ma


@pytest.mark.parametrize("fetcher_class", [AkshareFetcher, EfinanceFetcher])
def test_invalid_quote_rows_do_not_poison_statistics(fetcher_class):
    fetcher = fetcher_class.__new__(fetcher_class)
    frame = pd.DataFrame({
        "代码": ["600000", "000001", "000002", "000003", "000004", "600000"],
        "名称": ["普通股"] * 6,
        "最新价": [11, "-", 9, float("inf"), 10, 11],
        "昨收": [10, 10, 0, 10, 10, 10],
        "成交额": [100_000_000, 100, 100, 100, "0", 100_000_000],
    })
    stats = fetcher._calc_market_stats(frame)
    assert stats["up_count"] == 1
    assert stats["flat_count"] == 0
    assert stats["total_amount"] == 1.0
    assert fetcher._calc_market_stats(frame.drop(columns="昨收")) is None
    assert fetcher._calc_market_stats(frame.iloc[[1]]) is None


def test_vix_and_stale_equity_quotes_are_not_risk_on_index_gains():
    overview = MarketOverview(date="2026-10-09", indices=[
        MarketIndex(code="SPX", name="SPX", change_pct=-1, data_date="2026-10-09"),
        MarketIndex(code="VIX", name="VIX", change_pct=20, data_date="2026-10-09"),
        MarketIndex(code="DJI", name="DJI", change_pct=8, data_date="2026-10-08"),
    ])
    assert _analyzer("us")._equity_index_changes(overview) == [-1]


def test_missing_topix_is_visible_in_report_coverage():
    overview = MarketOverview(date="2026-10-09", indices=[MarketIndex(code="N225", name="日经")])
    note = _analyzer("jp")._index_coverage_note(overview)
    assert "TOPX" in note
    assert "不得" in note


def test_overview_uses_quote_date_instead_of_machine_date(monkeypatch):
    ma = _analyzer("us")
    ma._get_main_indices = MagicMock(return_value=[
        MarketIndex(code="SPX", name="SPX", data_date="2026-10-08"),
    ])
    monkeypatch.setattr("src.market_analyzer.get_market_now", lambda _region: datetime(2026, 10, 9))
    assert ma.get_market_overview().date == "2026-10-08"


@pytest.mark.parametrize("raw, expected", [(290.67, 2.9067), (0, 0), (-100, -1)])
def test_southbound_units_and_zero_are_preserved(monkeypatch, raw, expected):
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"result": {"data": [{"TRADE_DATE": "2026-10-09 00:00:00", "NET_DEAL_AMT": raw}]}},
    )
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr("data_provider.akshare_fetcher.requests.get", fake_get)
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    flow = fetcher.get_southbound_flow("2026-10-09")
    assert flow["net_buy"] == pytest.approx(expected)
    assert flow["unit"] == "HKD 100m"
    assert flow["metric"] == "net_executed_buy"
    assert calls[0][1]["params"]["pageSize"] == "1"
    assert calls[0][1]["timeout"] > 0
    overview = MarketOverview(date="2026-10-09", southbound_flow=flow)
    assert f"{expected:+.2f}" in _analyzer("hk")._build_southbound_block(overview)


@pytest.mark.parametrize("row", [
    {"TRADE_DATE": "2026-10-08", "NET_DEAL_AMT": 100},
    {"TRADE_DATE": "2026-10-09", "NET_DEAL_AMT": None},
    {"TRADE_DATE": "2026-10-09", "NET_DEAL_AMT": float("inf")},
])
def test_southbound_rejects_old_or_invalid_data(monkeypatch, row):
    monkeypatch.setattr("data_provider.akshare_fetcher.requests.get", lambda *args, **kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"result": {"data": [row]}},
    ))
    assert AkshareFetcher(sleep_min=0, sleep_max=0).get_southbound_flow("2026-10-09") is None


def test_rankings_timeout_falls_back_to_sina(monkeypatch):
    import sys

    eastmoney = object()
    sina = object()
    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_board_industry_name_em=eastmoney, stock_sector_spot=sina,
    ))
    calls = []

    def fake_call(func, **kwargs):
        calls.append((func, kwargs))
        if func is eastmoney:
            raise TimeoutError("slow provider")
        return pd.DataFrame({"板块": ["传媒", "建筑"], "涨跌幅": [2, -1]})

    monkeypatch.setattr("data_provider.akshare_fetcher._akshare_call_with_timeout", fake_call)
    top, bottom = AkshareFetcher(sleep_min=0, sleep_max=0).get_sector_rankings(1)
    assert top[0]["name"] == "传媒"
    assert bottom[0]["name"] == "建筑"
    assert all(call[1]["timeout"] == 30 for call in calls)
    assert calls[1][1]["indicator"] == "行业"


def test_absolute_turnover_is_not_called_volume_contraction():
    assert "不能据此判断缩量" in MarketAnalyzer._describe_turnover(5000)


def test_chinese_template_keeps_southbound_and_partial_index_notes():
    ma = _analyzer("hk")
    overview = MarketOverview(date="2026-10-09", indices=[
        MarketIndex(code="HSI", name="恒生指数", current=25000, data_date="2026-10-09"),
    ], southbound_flow={
        "data_date": "2026-10-09", "net_buy": 2.9067, "unit": "HKD 100m",
        "metric": "net_executed_buy", "source": "Eastmoney",
    })
    report = ma._generate_template_review(overview, [])
    assert "HSTECH" in report
    assert "+2.91" in report
    assert "2026-10-09" in report
