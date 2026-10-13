import json
import sys

import pytest

from scripts import daily_delivery_guard as guard
from scripts import send_daily_notifications as delivery


def test_only_current_unexpired_default_branch_receipt_suppresses_schedule():
    receipt = {"name": "daily-delivery-20261013", "expired": False, "workflow_run": {"head_branch": "main"}}
    env = {"GITHUB_EVENT_NAME": "schedule", "DEFAULT_BRANCH": "main"}
    assert guard.should_skip(env, lambda date: [receipt], "20261013")
    assert not guard.should_skip(env, lambda date: [receipt], "20261014")
    for change in ({"expired": True}, {"workflow_run": {"head_branch": "test"}}, {"name": "analysis-reports-26"}):
        assert not guard.should_skip(env, lambda date: [dict(receipt, **change)], "20261013")
    assert not guard.should_skip(env, lambda date: [], "20261013")


def test_manual_replay_bypasses_receipt_and_standard_has_no_backup_duplicates():
    def forbidden(date):
        raise AssertionError("Should not request artifacts")
    assert not guard.should_skip({"GITHUB_EVENT_NAME": "workflow_dispatch"}, forbidden, "20261013")
    env = {"GITHUB_EVENT_NAME": "schedule", "DAILY_NOTIFICATION_LAYOUT": "standard", "TRIGGER_SCHEDULE": "37 11 * * 1-5"}
    assert guard.should_skip(env, forbidden, "20261013")
    env["TRIGGER_SCHEDULE"] = "7 10 * * 1-5"
    assert not guard.should_skip(env, forbidden, "20261013")


def test_receipt_api_failure_continues_with_visible_warning(tmp_path, monkeypatch, capsys):
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("DEFAULT_BRANCH", "main")
    monkeypatch.setenv("DAILY_NOTIFICATION_LAYOUT", "two_part")
    def fail(date):
        raise OSError("unavailable")
    monkeypatch.setattr(guard, "fetch_artifacts", fail)
    guard.main()
    assert output.read_text() == "skip=false\n"
    assert "::warning::" in capsys.readouterr().out


@pytest.mark.parametrize("statuses,market,expected", [([True, True], True, True), ([False, True], True, False), ([True, False], True, False), ([True, True], False, False)])
def test_full_delivery_receipt_requires_both_cards_and_reports(tmp_path, monkeypatch, statuses, market, expected):
    from src.notification_sender.serverchan3_sender import Serverchan3Sender
    (tmp_path / "report_20261013.md").write_text("Stock report")
    if market:
        (tmp_path / "market_review_20261013.md").write_text("Market report")
    receipt = tmp_path / "delivery_receipt_20261013.json"
    receipt.write_text("old stale receipt")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(sys, "argv", ["send", "--date", "20261013", "--report-dir", str(tmp_path)])
    results = iter(statuses)
    monkeypatch.setattr(Serverchan3Sender, "send_to_serverchan3", lambda *args: next(results))
    assert delivery.main() == (0 if all(statuses) else 1)
    assert receipt.exists() == expected
    assert output.exists() == expected
    if expected:
        assert json.loads(receipt.read_text()) == {"date": "20261013", "status": "api_accepted", "cards": 2, "phone_delivery_confirmed": False}
        assert output.read_text() == "delivery_date=20261013\n"


def test_delivery_gate_and_timezone_are_wired_into_daily_workflow():
    from pathlib import Path
    import yaml
    workflow = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/00-daily-analysis.yml").read_text())
    jobs = workflow["jobs"]
    assert jobs["analyze"]["needs"] == "delivery_gate"
    assert jobs["analyze"]["if"] == "needs.delivery_gate.outputs.skip != 'true'"
    assert jobs["analyze"]["env"]["TZ"] == "Asia/Shanghai"
    upload = next(step for step in jobs["analyze"]["steps"] if step.get("name") == "上传接口接受回执")
    assert "delivery_date" in upload["if"] and "delivery_date" in upload["with"]["name"]
