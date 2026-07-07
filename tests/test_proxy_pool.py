"""ProxyPool tests (T3.4, ADR-0011, docs/04 §2.1).

Proves round-robin selection over healthy proxies, per-proxy health tallies, quarantine +
recovery on a fake clock, and the two "direct connection" cases: an empty pool, and every proxy
cooling down. Zero-proxy = direct is the local/harness default.
"""

from __future__ import annotations

from acquire_intel.resilience.proxy import ProxyPool


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_empty_pool_is_direct_connection() -> None:
    pool = ProxyPool(urls=())
    assert pool.acquire() is None
    # Recording against a direct connection is a harmless no-op.
    pool.record_success(None)
    pool.record_ban(None)


def test_round_robin_over_healthy_proxies() -> None:
    pool = ProxyPool(urls=["http://p1", "http://p2", "http://p3"])
    picks = [pool.acquire() for _ in range(4)]
    assert picks == ["http://p1", "http://p2", "http://p3", "http://p1"]


def test_blanks_and_duplicates_are_cleaned() -> None:
    pool = ProxyPool(urls=["http://p1", " ", "http://p1", "  http://p2  "])
    assert [pool.acquire() for _ in range(3)] == ["http://p1", "http://p2", "http://p1"]


def test_banned_proxy_is_quarantined_then_recovers() -> None:
    clock = _Clock()
    pool = ProxyPool(urls=["http://p1", "http://p2"], cooldown_seconds=30.0, clock=clock)

    pool.record_ban("http://p1")  # quarantine p1 for 30s
    # p1 is skipped while cooling down → only p2 is served.
    assert {pool.acquire() for _ in range(4)} == {"http://p2"}

    clock.advance(30.0)  # cool-down elapsed → p1 back in rotation
    assert "http://p1" in {pool.acquire() for _ in range(4)}


def test_all_quarantined_degrades_to_direct() -> None:
    pool = ProxyPool(urls=["http://p1", "http://p2"], cooldown_seconds=60.0, clock=_Clock())
    pool.record_ban("http://p1")
    pool.record_ban("http://p2")
    assert pool.acquire() is None  # every proxy cooling down → direct beats failing the crawl


def test_health_tracks_success_and_failure_rates() -> None:
    pool = ProxyPool(urls=["http://p1"])
    assert pool.health()[0].success_rate() == 1.0  # optimistic before any observation
    pool.record_success("http://p1")
    pool.record_success("http://p1")
    pool.record_ban("http://p1")
    health = {h.url: h for h in pool.health()}["http://p1"]
    assert (health.successes, health.failures) == (2, 1)
    assert health.success_rate() == 2 / 3
