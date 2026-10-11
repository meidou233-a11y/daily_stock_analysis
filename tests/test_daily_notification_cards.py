from scripts.send_daily_notifications import build_cards


def test_two_cards_preserve_every_stock_and_screening_details():
    stock = "# Dashboard\nAAPL summary\nNVDA summary\n---\n## AAPL\n### 📌 核心结论\nAAPL decision\n### 📈 当日行情\nAAPL quote\n### 🎯 作战计划\nAAPL plan\n### 📊 数据透视\nLong technical details\n---\n## NVDA\n### 📌 核心结论\nNVDA decision"
    first, second = build_cards(stock, "Market report", {
        "added": [{"code": "NVDA", "market": "us", "score": 80, "strategies": ["quality_value"]}],
        "warnings": ["cn: TimeoutExpired; fixed watchlist retained"],
    })
    assert "AAPL decision" in first and "NVDA decision" in first
    assert "AAPL quote" in first and "AAPL plan" in first
    assert "quality_value" in first and "80.00" in first and "TimeoutExpired" in first
    assert "Market report" in second and "AAPL summary" in second and "NVDA summary" in second
    assert "Long technical details" not in first


def test_missing_screening_and_market_are_disclosed():
    first, second = build_cards("# Dashboard", "", {})
    assert "无新增自动候选" in first
    assert "本次没有大盘报告" in second
