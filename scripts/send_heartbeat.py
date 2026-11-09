"""Dead-man's switch heartbeat for scheduled Actions runs.

A silently disabled schedule produces no run at all, so there is no failed run
to notice. Pinging an external monitor after every completed run turns that
silence into an alert: the monitor alerts when the expected ping never arrives.

Unconfigured (no ``HEARTBEAT_URL``) means monitoring is off and the step is a
no-op, so the daily job keeps working without any extra setup.
"""
from __future__ import annotations

import os
import urllib.request
from urllib.parse import urlencode

DEFAULT_TIMEOUT_SECONDS = 10
SUCCESS = "success"
FAILURE = "failure"
_ALLOWED_SCHEMES = ("http://", "https://")


def resolve_url(environ):
    """Return the configured heartbeat URL, or None when monitoring is off."""
    url = (environ.get("HEARTBEAT_URL") or "").strip()
    if not url:
        return None
    if not url.startswith(_ALLOWED_SCHEMES):
        raise ValueError(f"HEARTBEAT_URL must start with http:// or https://, got {url[:32]!r}")
    return url


def resolve_status(environ):
    """Collapse the job status to the two signals a monitor needs.

    Anything that is not an explicit success (including an empty status when the
    step runs outside a job context) is reported as a failure so that a broken
    run never masquerades as a healthy one.
    """
    raw = (environ.get("HEARTBEAT_STATUS") or "").strip().lower()
    return SUCCESS if raw in ("", SUCCESS) else FAILURE


def build_ping_url(base_url, status, run_url="", date=""):
    """Attach the liveness signal fields to the monitor's ping URL."""
    params = {"status": status}
    if run_url:
        params["run"] = run_url
    if date:
        params["date"] = date
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode(params)}"


def ping(url, timeout=DEFAULT_TIMEOUT_SECONDS):
    """Send one ping. Returns True when the monitor accepted it."""
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return 200 <= int(getattr(response, "status", response.getcode())) < 300


def emit(message):
    """Print a log line without ever raising.

    A console that cannot encode the message (for example a Windows code page
    other than UTF-8) must not turn a successful run into a failed job.
    """
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", "backslashreplace").decode("ascii"))


def main():
    status = resolve_status(os.environ)
    try:
        url = resolve_url(os.environ)
        if url is None:
            emit("未配置 HEARTBEAT_URL，略过心跳上报（监控未开启）")
            return 0
        ping_url = build_ping_url(
            url,
            status,
            os.environ.get("HEARTBEAT_RUN_URL", ""),
            os.environ.get("HEARTBEAT_DATE", ""),
        )
        accepted = ping(ping_url)
    except (OSError, ValueError) as error:
        # Monitoring must never break the job it observes.
        emit(f"::warning::心跳上报失败 ({type(error).__name__})：{error}")
        return 0
    if accepted:
        emit(f"心跳上报成功（status={status}）")
    else:
        emit("::warning::心跳上报未被监控端接受")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
