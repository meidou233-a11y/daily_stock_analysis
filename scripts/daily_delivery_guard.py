"""Skip scheduled duplicates only when a full two-card API receipt exists."""
from datetime import datetime
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


def has_receipt(artifacts, date, branch):
    return any(
        item.get("name") == f"daily-delivery-{date}"
        and item.get("expired") is False
        and item.get("workflow_run", {}).get("head_branch") == branch
        for item in artifacts
    )


def should_skip(environ, fetch_artifacts, date):
    # Manual full/replay always runs, including when the phone missed an API-accepted push.
    if environ.get("GITHUB_EVENT_NAME") != "schedule":
        return False
    if environ.get("DAILY_NOTIFICATION_LAYOUT", "two_part") != "two_part":
        # Standard channels have no two-card receipt; keep only their primary trigger.
        return environ.get("TRIGGER_SCHEDULE") == "37 11 * * 1-5"
    return has_receipt(fetch_artifacts(date), date, environ["DEFAULT_BRANCH"])


def fetch_artifacts(date):
    query = urlencode({"name": f"daily-delivery-{date}", "per_page": 100})
    url = f"{os.environ['GITHUB_API_URL']}/repos/{os.environ['GITHUB_REPOSITORY']}/actions/artifacts?{query}"
    request = Request(url, headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json",
    })
    with urlopen(request, timeout=15) as response:
        return json.load(response)["artifacts"]


def main():
    date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    try:
        skip = should_skip(os.environ, fetch_artifacts, date)
    except (OSError, ValueError, KeyError) as error:
        # An unavailable receipt API must not suppress a missing daily report.
        print(f"::warning::推送回执检查失败 ({type(error).__name__})，继续分析；可能重复推送")
        skip = False
    print(f"日报 {date}：{'跳过本次定时任务' if skip else '继续分析/补发'}")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"skip={str(skip).lower()}\n")


if __name__ == "__main__":
    main()
