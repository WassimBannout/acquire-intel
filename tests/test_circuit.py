"""Pure circuit-breaker state-machine tests (T3.3, docs/04 §2.4).

A fake clock makes trip + cool-down deterministic: closed → open after the failure threshold,
open refuses requests during the cool-down, then half-open allows a single probe that either
closes (success) or re-opens (failure).
"""

from __future__ import annotations

from acquire_intel.resilience.circuit import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitState,
)


class _Clock:
    """A manually-advanced monotonic clock."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(clock: _Clock, *, threshold: int = 3, cooldown: float = 60.0) -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=threshold, cooldown_seconds=cooldown, clock=clock)


def test_closed_allows_and_stays_closed_below_threshold() -> None:
    breaker = _breaker(_Clock(), threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.allow()


def test_trips_open_at_threshold_and_refuses() -> None:
    breaker = _breaker(_Clock(), threshold=3)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    assert not breaker.allow()  # refused during cool-down


def test_success_resets_the_failure_count() -> None:
    breaker = _breaker(_Clock(), threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()  # count restarted → still one short of tripping
    assert breaker.state is CircuitState.CLOSED


def test_cooldown_elapses_to_half_open_then_closes_on_success() -> None:
    clock = _Clock()
    breaker = _breaker(clock, threshold=2, cooldown=60.0)
    breaker.record_failure()
    breaker.record_failure()
    assert not breaker.allow()  # open, still cooling

    clock.advance(60.0)
    assert breaker.allow()  # cool-down elapsed → half-open probe permitted
    assert breaker.state is CircuitState.HALF_OPEN

    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED
    assert breaker.allow()


def test_half_open_probe_failure_reopens() -> None:
    clock = _Clock()
    breaker = _breaker(clock, threshold=2, cooldown=30.0)
    breaker.record_failure()
    breaker.record_failure()
    clock.advance(30.0)
    assert breaker.allow()  # half-open
    breaker.record_failure()  # probe failed
    assert breaker.state is CircuitState.OPEN
    assert not breaker.allow()  # cooling again from the new trip


def test_registry_isolates_domains() -> None:
    clock = _Clock()
    registry = CircuitBreakerRegistry(failure_threshold=1, cooldown_seconds=10.0, clock=clock)
    registry.for_domain("a.example").record_failure()
    assert registry.for_domain("a.example").state is CircuitState.OPEN
    assert registry.for_domain("b.example").state is CircuitState.CLOSED
    assert registry.for_domain("b.example").allow()
