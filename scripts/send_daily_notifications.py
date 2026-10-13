"""Deliver two daily report cards using saved reports and the existing sender."""
import argparse
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build_cards(stock_report, market_report, pool):
    """Keep all stocks; retain core conclusions, quotes and plans in the dashboard."""
    sections = stock_report.split("\n---\n") if stock_report else []
    overview = sections[0] if sections else "本次没有个股报告。"
    dashboard = [overview]
    for section in sections[1:]:
        heading = re.search(r"^## .+$", section, re.MULTILINE)
        if not heading:
            continue
        selected = []
        for block in re.split(r"(?=^### )", section, flags=re.MULTILINE):
            if block.startswith(("### 📌 核心结论", "### 📈 当日行情", "### 🎯 作战计划")):
                selected.append(block.strip())
        if selected:
            dashboard.append(heading.group(0) + "\n\n" + "\n\n".join(selected))
        else:
            dashboard.append(section.strip())
    screening = ["## 每日智慧选股", "自动候选供研究，筛选命中不等于买入信号。"]
    candidates = pool.get("added", [])
    if candidates:
        for row in candidates:
            screening.append(
                f"- **{row['code']}** | 市场 {row.get('market', '未知')} | "
                f"筛选分数 {float(row.get('score', 0)):.2f} | "
                f"命中：{', '.join(row.get('matched_strategies', row.get('strategies', []))) or '未提供'}"
            )
    else:
        screening.append("本轮无新增自动候选；固定自选仍保留。")
    for warning in pool.get("warnings", []):
        screening.append(f"- 筛选降级：{warning}")
    dashboard.append("\n".join(screening))
    first = "\n\n---\n\n".join(dashboard)
    second = "# 大盘复盘与个股概况\n\n" + (market_report or "本次没有大盘报告。")
    if stock_report:
        second += "\n\n---\n\n## 个股情况\n\n" + overview
    return first, second


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports")
    parser.add_argument("--date", default=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"))
    args = parser.parse_args()
    if not re.fullmatch(r"\d{8}", args.date):
        parser.error("date must be YYYYMMDD")
    receipt = args.report_dir / f"delivery_receipt_{args.date}.json"
    receipt.unlink(missing_ok=True)
    def read(name):
        path = args.report_dir / name
        return path.read_text(encoding="utf-8") if path.exists() else ""
    stock = read(f"report_{args.date}.md")
    market = read(f"market_review_{args.date}.md")
    if not stock and not market:
        parser.error("no saved reports for the requested date")
    pool_text = read("daily_stock_pool.json")
    pool = json.loads(pool_text) if pool_text else {}
    cards = build_cards(stock, market, pool)
    # Validate both before sending; never silently split or truncate a report.
    if any(len(card.encode("utf-8")) > 60_000 for card in cards):
        parser.error("report card exceeds the conservative single-message budget; full reports retained")
    from src.notification_sender.serverchan3_sender import Serverchan3Sender
    sender = Serverchan3Sender(SimpleNamespace(serverchan3_sendkey=os.getenv("SERVERCHAN3_SENDKEY")))
    statuses = []
    for name, title, content in zip(
        ("dashboard_notification", "market_stocks_notification"),
        ("自选股仪表盘与每日智慧选股", "大盘复盘与个股情况"), cards,
    ):
        (args.report_dir / f"{name}_{args.date}.md").write_text(content, encoding="utf-8")
        statuses.append(sender.send_to_serverchan3(content, f"{args.date} {title}"))
    accepted = all(statuses)
    if accepted and stock and market:
        receipt.write_text(json.dumps({
            "date": args.date, "status": "api_accepted", "cards": len(cards),
            "phone_delivery_confirmed": False,
        }), encoding="utf-8")
        if os.getenv("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write(f"delivery_date={args.date}\n")
    logging.info("日报 %s：%d 条，接口全部接受=%s", args.date, len(cards), accepted)
    return 0 if accepted else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
