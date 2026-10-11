from scripts.analysis_health_summary import build_summary


def test_health_summary_distinguishes_missing_data_and_never_copies_secrets():
    summary, count = build_summary(
        "Anspire 余额不足 secret-token\n"
        "prepayment credits are depleted\n"
        "action=get_market_stats status=empty\n"
        "action=get_sector_rankings status=success\n"
        "[概念排行] 所有数据源均失败\n"
    )
    assert count == 4
    assert "secret-token" not in summary
    assert "行业榜采集缺失" not in summary
    assert "市场宽度/成交额采集缺失" in summary


def test_absent_logs_are_not_reported_as_healthy():
    summary, count = build_summary("")
    assert count == 0
    assert "无可用日志" in summary


def test_no_known_warning_does_not_certify_complete_data():
    summary, count = build_summary("notification success")
    assert count == 0
    assert "不代表所有数据均可用" in summary
