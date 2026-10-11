"""Summarize observed degradation without exposing raw log messages or secrets."""

import argparse
from pathlib import Path
import re


CHECKS = (
    ("新闻账户余额/额度不足", r"余额不足|额度不足|免费额度: 0\.00"),
    ("LLM 预付额度耗尽", r"prepayment credits are depleted"),
    ("市场宽度/成交额采集缺失", r"action=get_market_stats status=(?:empty|failed)"),
    ("行业榜采集缺失", r"action=get_sector_rankings status=(?:empty|failed)"),
    ("概念榜采集缺失", r"action=get_concept_rankings status=(?:empty|failed)|\[概念排行\] 所有数据源均失败"),
    ("TOPIX 行情源异常", r"\^TOPX.*(?:404|no price data|no timezone)|获取日本指数 东证指数 失败"),
)


def build_summary(log_text):
    observed = [label for label, pattern in CHECKS if re.search(pattern, log_text, re.IGNORECASE)]
    lines = ["## 分析数据健康检查", "", "任务完成不等于数据完整；以下为日志中检测到的降级信号。", ""]
    lines.extend(f"- ⚠️ {label}" for label in observed)
    if not log_text.strip():
        lines.append("- 无可用日志，无法检查数据健康。")
    elif not observed:
        lines.append("- 未检测到已登记的降级信号；不代表所有数据均可用。")
    return "\n".join(lines) + "\n", len(observed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--summary-file")
    args = parser.parse_args()
    log_text = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                         for path in sorted(Path(args.log_dir).glob("stock_analysis_*.log")))
    summary, count = build_summary(log_text)
    print(summary)
    if args.summary_file:
        with Path(args.summary_file).open("a", encoding="utf-8") as output:
            output.write(summary)
    if count:
        print(f"::warning::分析完成，但检测到 {count} 类数据降级信号；请查看运行摘要。")


if __name__ == "__main__":
    main()
