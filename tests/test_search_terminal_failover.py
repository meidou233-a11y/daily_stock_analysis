"""Quota failures must stop repeated calls and preserve fallback coverage."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.search_service import AnspireSearchProvider, SearchResponse, SearchResult, SearchService


def _http(status, body):
    return SimpleNamespace(status_code=status, text=str(body), json=lambda: body,
                           headers={"content-type": "application/json"})


@pytest.mark.parametrize("response", [
    _http(401, {"msg": "可用余额不足，当前可用免费额度: 0.00"}),
    _http(200, {"code": -1, "msg": "余额不足"}),
])
def test_exhausted_anspire_key_is_not_retried_in_same_run(monkeypatch, response):
    request = MagicMock(return_value=response)
    monkeypatch.setattr("src.search_service._get_with_retry", request)
    provider = AnspireSearchProvider(["test-key"])
    assert not provider.search("A股").success
    assert not provider.is_available
    assert not provider.search("港股").success
    assert request.call_count == 1


def test_terminal_key_does_not_disable_other_keys(monkeypatch):
    request = MagicMock(side_effect=[
        _http(401, {"msg": "invalid key"}),
        _http(200, {"code": 200, "results": []}),
    ])
    monkeypatch.setattr("src.search_service._get_with_retry", request)
    provider = AnspireSearchProvider(["bad-key", "good-key"])
    assert not provider.search("A股").success
    assert provider.is_available
    assert provider.search("港股").success
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer good-key"


def test_transient_failure_remains_retryable(monkeypatch):
    monkeypatch.setattr("src.search_service._get_with_retry", lambda *a, **kw: _http(500, {}))
    provider = AnspireSearchProvider(["test-key"])
    assert not provider.search("A股").success
    assert provider.is_available


def test_comprehensive_intel_falls_back_within_same_dimension():
    service = SearchService(searxng_public_instances_enabled=False)
    failed = SimpleNamespace(name="Broken", is_available=True, search=MagicMock(return_value=SearchResponse(
        query="", provider="Broken", results=[], success=False,
    )))
    good = SimpleNamespace(name="Backup", is_available=True, search=MagicMock(return_value=SearchResponse(
        query="", provider="Backup", success=True, results=[SearchResult(
            title="贵州茅台 600519 发布经营公告", snippet="贵州茅台 600519 披露最新经营情况",
            url="https://example.com/600519/news", source="example.com", published_date=date.today().isoformat(),
        )],
    )))
    service._providers = [failed, good]
    result = service.search_comprehensive_intel("600519", "贵州茅台", max_searches=1)
    assert result["latest_news"].success
    assert result["latest_news"].results
    assert good.search.call_count == 1
    assert good.search.call_args.kwargs["days"] == service._effective_news_window_days()


def test_failed_search_context_does_not_claim_no_news():
    response = SearchResponse(query="A股", provider="Broken", results=[], success=False)
    assert "失败" in response.to_context()
    assert "未找到" not in response.to_context()
    report = SearchService(searxng_public_instances_enabled=False).format_intel_report(
        {"latest_news": response}, "市场",
    )
    assert "检索失败" in report
