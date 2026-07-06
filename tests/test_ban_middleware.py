"""Gating tests for BanDetectionMiddleware (T3.2, ADR-0005, docs/04 §2.5).

The middleware must: pass ``ok`` responses through untouched; and for a ban, record it (stats +
a ``BanEvent`` on the spider sink) and raise ``IgnoreRequest`` so the extractor never sees it.
Robots.txt fetches are never gated.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from scrapy.exceptions import IgnoreRequest
from scrapy.http import Request, TextResponse

from acquire_intel.contracts import BanEvent
from acquire_intel.resilience.middleware import STAT_BAN_EVENTS, BanDetectionMiddleware

_URL = "https://shop.example.com/products.json"


class _FakeStats:
    """A minimal stats collector recording ``inc_value`` calls."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def inc_value(self, key: str, count: int = 1, start: int = 0) -> None:
        self.counts[key] = self.counts.get(key, start) + count


def _spider() -> Any:
    return SimpleNamespace(name="demo_rest", ban_events=[])


def _response(status: int, body: bytes, *, meta: dict[str, Any] | None = None) -> TextResponse:
    request = Request(_URL, meta=meta or {})
    return TextResponse(url=_URL, status=status, body=body, request=request, encoding="utf-8")


def test_ok_response_passes_through_untouched() -> None:
    mw = BanDetectionMiddleware(stats=_FakeStats())
    spider = _spider()
    resp = _response(200, b'{"products": [{"id": 1}]}')

    assert mw.process_response(resp.request, resp, spider) is resp
    assert spider.ban_events == []


def test_blocked_response_is_dropped_and_recorded() -> None:
    stats = _FakeStats()
    mw = BanDetectionMiddleware(stats=stats)
    spider = _spider()
    resp = _response(403, b"<html>403 Forbidden</html>")

    with pytest.raises(IgnoreRequest):
        mw.process_response(resp.request, resp, spider)

    assert stats.counts[STAT_BAN_EVENTS] == 1
    assert stats.counts["acquire/ban/blocked"] == 1
    (event,) = spider.ban_events
    assert isinstance(event, BanEvent)
    assert event.kind == "blocked"
    assert event.action_taken == "rotate_identity"
    assert event.http_status == 403


def test_captcha_response_is_dropped_with_captcha_kind() -> None:
    stats = _FakeStats()
    mw = BanDetectionMiddleware(stats=stats)
    spider = _spider()
    resp = _response(200, b"<html>Please verify you are human (captcha)</html>")

    with pytest.raises(IgnoreRequest):
        mw.process_response(resp.request, resp, spider)

    assert stats.counts["acquire/ban/captcha"] == 1
    assert spider.ban_events[0].kind == "captcha"


def test_soft_ban_empty_body_is_dropped_as_empty() -> None:
    stats = _FakeStats()
    mw = BanDetectionMiddleware(stats=stats)
    spider = _spider()
    resp = _response(200, b"")

    with pytest.raises(IgnoreRequest):
        mw.process_response(resp.request, resp, spider)

    assert stats.counts["acquire/ban/empty"] == 1


def test_robots_txt_fetch_is_never_gated() -> None:
    stats = _FakeStats()
    mw = BanDetectionMiddleware(stats=stats)
    spider = _spider()
    # A 404 robots.txt would otherwise classify as blocked; the guard passes it through.
    resp = _response(404, b"Not Found", meta={"dont_obey_robotstxt": True})

    assert mw.process_response(resp.request, resp, spider) is resp
    assert stats.counts == {}
    assert spider.ban_events == []


def test_works_without_a_stats_collector() -> None:
    # from_crawler may hand None; recording must not blow up.
    mw = BanDetectionMiddleware(stats=None)
    spider = _spider()
    resp = _response(429, b"slow down")

    with pytest.raises(IgnoreRequest):
        mw.process_response(resp.request, resp, spider)
    assert spider.ban_events[0].kind == "rate_limited"
