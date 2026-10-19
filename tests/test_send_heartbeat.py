from pathlib import Path

import pytest
import yaml

from scripts import send_heartbeat as heartbeat

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/00-daily-analysis.yml"
KEEPALIVE = Path(__file__).resolve().parents[1] / ".github/workflows/actions-keepalive.yml"


def test_unconfigured_heartbeat_is_a_noop():
    assert heartbeat.resolve_url({}) is None
    assert heartbeat.resolve_url({"HEARTBEAT_URL": "   "}) is None


def test_non_http_heartbeat_url_is_rejected():
    with pytest.raises(ValueError):
        heartbeat.resolve_url({"HEARTBEAT_URL": "ftp://example.test/ping"})


@pytest.mark.parametrize(
    "raw,expected",
    [("", "success"), ("success", "success"), ("SUCCESS", "success"), ("failure", "failure"), ("cancelled", "failure")],
)
def test_unknown_or_empty_status_is_never_reported_as_healthy(raw, expected):
    assert heartbeat.resolve_status({"HEARTBEAT_STATUS": raw}) == expected


def test_ping_url_appends_fields_without_dropping_existing_query():
    assert heartbeat.build_ping_url("https://hc.test/ping/abc", "success") == (
        "https://hc.test/ping/abc?status=success"
    )
    url = heartbeat.build_ping_url("https://hc.test/ping/abc?grace=60", "failure", "https://run/1", "20261016")
    assert url.startswith("https://hc.test/ping/abc?grace=60&status=failure")
    assert "run=https%3A%2F%2Frun%2F1" in url
    assert "date=20261016" in url


def test_unconfigured_run_never_calls_the_network(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Should not ping without HEARTBEAT_URL")

    monkeypatch.delenv("HEARTBEAT_URL", raising=False)
    monkeypatch.setattr(heartbeat, "ping", forbidden)
    assert heartbeat.main() == 0
    assert "略过心跳上报" in capsys.readouterr().out


def test_transport_failure_warns_but_never_fails_the_job(monkeypatch, capsys):
    def boom(url, timeout=heartbeat.DEFAULT_TIMEOUT_SECONDS):
        raise OSError("unavailable")

    monkeypatch.setenv("HEARTBEAT_URL", "https://hc.test/ping/abc")
    monkeypatch.setenv("HEARTBEAT_STATUS", "failure")
    monkeypatch.setattr(heartbeat, "ping", boom)
    assert heartbeat.main() == 0
    assert "::warning::" in capsys.readouterr().out


def test_successful_ping_reports_the_job_status(monkeypatch, capsys):
    seen = {}

    def record(url, timeout=heartbeat.DEFAULT_TIMEOUT_SECONDS):
        seen["url"] = url
        return True

    monkeypatch.setenv("HEARTBEAT_URL", "https://hc.test/ping/abc")
    monkeypatch.setenv("HEARTBEAT_STATUS", "success")
    monkeypatch.setattr(heartbeat, "ping", record)
    assert heartbeat.main() == 0
    assert "status=success" in seen["url"]
    assert "心跳上报成功" in capsys.readouterr().out


def test_emit_falls_back_when_console_cannot_encode(monkeypatch):
    """A non-UTF-8 console (for example Windows cp950) must not fail the job."""
    calls = []

    def fake_print(message, *args, **kwargs):
        calls.append(message)
        if len(calls) == 1:
            raise UnicodeEncodeError("cp950", message, 0, 1, "illegal multibyte sequence")

    monkeypatch.setattr("builtins.print", fake_print)
    heartbeat.emit("心跳上报成功")
    assert len(calls) == 2
    assert calls[1].isascii()


def test_heartbeat_is_wired_into_daily_workflow_as_always_and_opt_in():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["analyze"]["steps"]
    step = next(item for item in steps if item.get("name") == "心跳上报（静默失效监控）")
    assert step["if"] == "always()"
    assert step["run"] == "python scripts/send_heartbeat.py"
    # ping URL 内含密钥，因此 Secrets 必须优先于 Variables。
    assert step["env"]["HEARTBEAT_URL"] == "${{ secrets.HEARTBEAT_URL || vars.HEARTBEAT_URL }}"
    assert step["env"]["HEARTBEAT_STATUS"] == "${{ job.status }}"


def test_keepalive_is_scheduled_opt_in_and_never_blocks_others():
    workflow = yaml.safe_load(KEEPALIVE.read_text(encoding="utf-8"))
    triggers = workflow["on"] if "on" in workflow else workflow[True]
    assert [entry["cron"] for entry in triggers["schedule"]] == ["23 3 * * 1"]
    assert "workflow_dispatch" in triggers
    assert workflow["concurrency"] == {"group": "actions-keepalive", "cancel-in-progress": False}
    step = workflow["jobs"]["keepalive"]["steps"][0]
    assert step["env"]["GH_TOKEN"] == "${{ secrets.KEEPALIVE_TOKEN }}"
    assert workflow["jobs"]["keepalive"]["timeout-minutes"] == 10
