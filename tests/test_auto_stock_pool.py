import json
from unittest import mock

import pandas as pd

from scripts.prepare_daily_stock_pool import prepare
from src.services.auto_stock_pool import canonical_code, merge_daily_pool, screen_snapshot


def test_hong_kong_codes_preserve_exchange_and_five_digits():
    assert canonical_code("0700.HK", "hk") == "hk00700"
    assert canonical_code("80700.HK", "hk") == "hk80700"
    assert canonical_code("NVDA", "hk") == ""


def test_fixed_us_codes_are_deduplicated_case_insensitively():
    codes, _ = merge_daily_pool("nvda", "NVDA,SNDK", {})
    assert codes == ["nvda", "SNDK"]


def test_round_robin_preserves_fixed_stocks_and_bounds_additions():
    codes, added = merge_daily_pool("600519,NVDA", "NVDA,SNDK", {
        "cn": [{"code": "600519"}, {"code": "000001"}, {"code": "600000"}],
        "hk": [{"code": "0700.HK"}],
        "us": [{"code": "NVDA"}, {"code": "AAPL"}],
    }, limit=3)
    assert codes == ["600519", "NVDA", "SNDK", "000001", "hk00700", "AAPL"]
    assert len(added) == 3
    assert merge_daily_pool("600519,NVDA", "SNDK", {}, limit=5)[0] == ["600519", "NVDA", "SNDK"]


def test_missing_valuation_does_not_pass_quality_filter():
    snapshot = pd.DataFrame([dict(code="AAPL", name="Apple", price=100, amount=1e9,
                                 total_mv=1e11, pe_ratio=None, pb_ratio=2,
                                 change_pct=1, volume_ratio=2, turnover_rate=1)])
    candidates, _ = screen_snapshot(snapshot, "us", {
        "quality_value": {"exclude_st": False, "market_cap_max": None},
    })
    assert candidates == []


def test_enabled_styles_are_combined_independently():
    snapshot = pd.DataFrame([dict(code="AAPL", name="Apple", price=100, amount=1e9,
                                 total_mv=1e11, pe_ratio=15, pb_ratio=2,
                                 change_pct=1, volume_ratio=2, turnover_rate=1)])
    candidates, warnings = screen_snapshot(snapshot, "us", {
        "quality_value": {"exclude_st": False},
        "momentum_quality": {"exclude_st": False},
    })
    assert not warnings
    assert candidates[0]["code"] == "AAPL"
    assert set(candidates[0]["strategies"]) == {"quality_value", "momentum_quality"}


def test_worker_failure_keeps_fixed_watchlist(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_LIST", "600519")
    monkeypatch.setenv("STOCK_LIST_EXTRA", "NVDA,SNDK")
    monkeypatch.setenv("AUTO_SCREEN_ENABLED", "true")
    monkeypatch.setenv("AUTO_SCREEN_MARKETS", "hk")
    output = tmp_path / "pool.txt"
    with mock.patch("scripts.prepare_daily_stock_pool.subprocess.run") as run:
        run.return_value.returncode = 1
        prepare(str(output))
    assert output.read_text() == "600519,NVDA,SNDK"
    assert json.loads(output.with_suffix(".json").read_text())["warnings"]


def test_invalid_addition_limit_keeps_fixed_watchlist(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_LIST", "600519")
    monkeypatch.setenv("AUTO_SCREEN_ENABLED", "false")
    monkeypatch.setenv("AUTO_SCREEN_MAX_ADDITIONS", "invalid")
    output = tmp_path / "pool.txt"
    prepare(str(output))
    assert output.read_text() == "600519"
    assert "Invalid AUTO_SCREEN_MAX_ADDITIONS" in output.with_suffix(".json").read_text()


def test_timeout_keeps_completed_strategy_candidates(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setenv("STOCK_LIST", "600519")
    monkeypatch.setenv("AUTO_SCREEN_ENABLED", "true")
    monkeypatch.setenv("AUTO_SCREEN_MARKETS", "us")
    monkeypatch.setenv("AUTO_SCREEN_MAX_ADDITIONS", "5")

    def timeout_after_checkpoint(command, **kwargs):
        from pathlib import Path
        Path(command[-1]).write_text(json.dumps({"candidates": [{"code": "AAPL"}], "warnings": []}))
        raise subprocess.TimeoutExpired(command, 90)

    output = tmp_path / "pool.txt"
    with mock.patch("scripts.prepare_daily_stock_pool.subprocess.run", side_effect=timeout_after_checkpoint):
        prepare(str(output))
    assert output.read_text() == "600519,AAPL"
    assert "TimeoutExpired" in output.with_suffix(".json").read_text()


def test_snapshot_only_style_is_not_restricted_to_daily_limit():
    snapshot = pd.DataFrame([dict(code=code, name=code, price=100, amount=amount,
                                 total_mv=1e11, pe_ratio=15, pb_ratio=2,
                                 change_pct=1, volume_ratio=2, turnover_rate=1)
                             for code, amount in [("AAPL", 1e9), ("MSFT", 9e8)]])
    candidates, warnings = screen_snapshot(snapshot, "us", {"quality_value": {"exclude_st": False}}, daily_limit=1)
    assert not warnings
    assert {row["code"] for row in candidates} == {"AAPL", "MSFT"}
