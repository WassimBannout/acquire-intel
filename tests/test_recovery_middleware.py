"""BackoffRetry + CircuitBreaker middleware tests (T3.3, ADR-0005, docs/04 §2.4).

The retry *decision* is exercised synchronously (``plan_retry``); the async ``process_response``
is driven once with an injected no-op sleep. The backoff recovery is also proven against the real
harness ``rate_limited`` sequence (429·burst → 200). The breaker is driven to a trip and then a
short-circuit, with a fake clock for the cool-down.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from scrapy.exceptions import IgnoreRequest
from scrapy.http import Request, TextResponse

from acquire_intel.resilience.backoff import BackoffPolicy
from acquire_intel.resilience.circuit import CircuitBreakerRegistry
from acquire_intel.resilience.middleware import (
    STAT_BACKOFF_EXHAUSTED,
    STAT_BACKOFF_RETRIES,
    STAT_CIRCUIT_SKIPPED,
    STAT_CIRCUIT_TRIPPED,
    BackoffRetryMiddleware,
    CircuitBreakerMiddleware,
)
from harness import HarnessConfig, create_harness_app

_URL = "https://shop.example.com/products.json"


class _FakeStats:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def inc_value(self, key: str, count: int = 1, start: int = 0) -> None:
        self.counts[key] = self.counts.get(key, start) + count


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _spider() -> Any:
    return SimpleNamespace(name="demo_rest", ban_events=[])


def _resp(
    status: int,
    *,
    body: bytes = b"x",
    url: str = _URL,
    meta: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> TextResponse:
    request = Request(url, meta=meta or {})
    return TextResponse(
        url=url, status=status, body=body, request=request, encoding="utf-8", headers=headers or {}
    )


async def _noop_sleep(_: float) -> None:
    return None


# --- BackoffRetryMiddleware ---------------------------------------------------


def _backoff(stats: _FakeStats | None = None, max_retries: int = 3) -> BackoffRetryMiddleware:
    return BackoffRetryMiddleware(
        BackoffPolicy(base_delay=0.01, max_delay=0.05, max_retries=max_retries),
        stats=stats,
    )


def test_ok_response_is_not_retried() -> None:
    assert _backoff().plan_retry(_resp(200).request, _resp(200)) is None


@pytest.mark.parametrize("status", [429, 503])
def test_retryable_statuses_produce_a_plan(status: int) -> None:
    mw = _backoff()
    resp = _resp(status)
    plan = mw.plan_retry(resp.request, resp)
    assert plan is not None
    assert plan.request.meta["backoff_retries"] == 1
    assert plan.request.dont_filter is True
    assert 0.0 <= plan.delay <= 0.05


def test_retry_after_header_is_honoured_as_a_floor() -> None:
    mw = _backoff()
    resp = _resp(429, headers={"Retry-After": "0.05"})
    plan = mw.plan_retry(resp.request, resp)
    assert plan is not None
    assert plan.delay >= 0.05


def test_retries_are_bounded_then_exhausted() -> None:
    stats = _FakeStats()
    mw = _backoff(stats, max_retries=2)
    # A request that has already been retried max_retries times is not retried again.
    resp = _resp(429, meta={"backoff_retries": 2})
    assert mw.plan_retry(resp.request, resp) is None
    assert stats.counts[STAT_BACKOFF_EXHAUSTED] == 1


def test_async_process_response_returns_retry_request_then_passes() -> None:
    stats = _FakeStats()
    mw = _backoff(stats)
    mw._sleep = _noop_sleep
    spider = _spider()

    retry = asyncio.run(mw.process_response(_resp(429).request, _resp(429), spider))
    assert isinstance(retry, Request)
    assert stats.counts[STAT_BACKOFF_RETRIES] == 1

    ok = _resp(200)
    passed = asyncio.run(mw.process_response(ok.request, ok, spider))
    assert passed is ok


def test_backoff_recovers_the_real_harness_rate_limit_sequence() -> None:
    # burst=2 → the harness serves 429, 429, then 200 for one identity.
    app = create_harness_app(HarnessConfig(rate_limited_burst=2, retry_after_seconds=0))
    app.testing = True
    stats = _FakeStats()
    mw = _backoff(stats, max_retries=3)

    retries = 0
    meta: dict[str, Any] = {}
    with app.test_client() as client:
        for _ in range(5):  # generous bound; must converge well within
            r = client.get("/rate_limited/products.json")
            resp = _resp(r.status_code, body=r.data or b"", meta=dict(meta))
            plan = mw.plan_retry(resp.request, resp)
            if plan is None:
                break
            retries += 1
            meta = dict(plan.request.meta)

    assert r.status_code == 200  # eventually succeeded
    assert retries == 2  # exactly the burst was retried away


# --- CircuitBreakerMiddleware -------------------------------------------------


def _circuit(
    clock: _Clock, stats: _FakeStats, *, threshold: int = 3, cooldown: float = 30.0
) -> CircuitBreakerMiddleware:
    registry = CircuitBreakerRegistry(
        failure_threshold=threshold, cooldown_seconds=cooldown, clock=clock
    )
    return CircuitBreakerMiddleware(registry, stats=stats)


def test_closed_circuit_allows_requests() -> None:
    mw = _circuit(_Clock(), _FakeStats())
    assert mw.process_request(_resp(200).request, _spider()) is None


def test_repeated_blocks_trip_then_short_circuit() -> None:
    stats = _FakeStats()
    mw = _circuit(_Clock(), stats, threshold=3)
    spider = _spider()

    for _ in range(3):
        blocked = _resp(403, body=b"Forbidden")
        assert mw.process_response(blocked.request, blocked, spider) is blocked
    assert stats.counts[STAT_CIRCUIT_TRIPPED] == 1

    # Now the domain is open: further requests are short-circuited (stop hammering).
    with pytest.raises(IgnoreRequest):
        mw.process_request(_resp(200).request, spider)
    assert stats.counts[STAT_CIRCUIT_SKIPPED] == 1


def test_cooldown_allows_a_probe_and_success_closes() -> None:
    clock = _Clock()
    stats = _FakeStats()
    mw = _circuit(clock, stats, threshold=2, cooldown=30.0)
    spider = _spider()

    for _ in range(2):
        blocked = _resp(403, body=b"Forbidden")
        mw.process_response(blocked.request, blocked, spider)
    with pytest.raises(IgnoreRequest):
        mw.process_request(_resp(200).request, spider)

    clock.advance(30.0)  # cool-down elapsed
    assert mw.process_request(_resp(200).request, spider) is None  # half-open probe allowed

    ok = _resp(200, body=b'{"products": []}')
    mw.process_response(ok.request, ok, spider)
    # Closed again → normal flow resumes.
    assert mw.process_request(_resp(200).request, spider) is None


def test_rate_limited_does_not_trip_the_breaker() -> None:
    stats = _FakeStats()
    mw = _circuit(_Clock(), stats, threshold=2)
    spider = _spider()
    for _ in range(5):
        r = _resp(429)
        mw.process_response(r.request, r, spider)
    assert STAT_CIRCUIT_TRIPPED not in stats.counts  # 429s are backoff's job, not the breaker's


def test_infra_requests_bypass_the_breaker() -> None:
    mw = _circuit(_Clock(), _FakeStats(), threshold=1)
    spider = _spider()
    infra = _resp(403, body=b"Forbidden", meta={"dont_obey_robotstxt": True})
    mw.process_response(infra.request, infra, spider)
    # Even after a "block", an infra request is never short-circuited.
    assert mw.process_request(infra.request, spider) is None
