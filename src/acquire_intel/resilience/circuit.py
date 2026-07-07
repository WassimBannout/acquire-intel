"""Per-domain circuit breaker (T3.3, ADR-0005, docs/04 §2.4).

After repeated blocks from a domain, stop hammering it: **open** the breaker and refuse requests
for a cool-down, then allow a single probe (**half-open**) and **close** again on success. A pure
state machine with an injectable clock, so trip + cool-down are deterministically testable without
real time. The Scrapy wiring lives in :mod:`.middleware`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class CircuitState(StrEnum):
    CLOSED = "closed"  # healthy — requests flow
    OPEN = "open"  # tripped — requests refused until the cool-down elapses
    HALF_OPEN = "half_open"  # cooling done — one probe allowed to test recovery


@dataclass
class CircuitBreaker:
    """One domain's breaker. ``clock`` returns monotonic seconds (injected in tests)."""

    failure_threshold: int
    cooldown_seconds: float
    clock: Callable[[], float] = time.monotonic
    state: CircuitState = CircuitState.CLOSED
    _failures: int = 0
    _opened_at: float | None = None

    def allow(self) -> bool:
        """Whether a request may proceed now (may transition OPEN → HALF_OPEN)."""
        if self.state is CircuitState.OPEN:
            assert self._opened_at is not None
            if self.clock() - self._opened_at >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN  # let a single probe through
                return True
            return False
        return True  # CLOSED or HALF_OPEN

    def record_success(self) -> None:
        """A good response — reset to healthy."""
        self.state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        """A block — count it; trip on threshold, or immediately if a half-open probe failed."""
        if self.state is CircuitState.HALF_OPEN:
            self._trip()
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self.state = CircuitState.OPEN
        self._opened_at = self.clock()
        self._failures = 0


@dataclass
class CircuitBreakerRegistry:
    """Lazily-created breakers keyed by domain, sharing one policy + clock."""

    failure_threshold: int
    cooldown_seconds: float
    clock: Callable[[], float] = time.monotonic
    _breakers: dict[str, CircuitBreaker] = field(default_factory=dict)

    def for_domain(self, domain: str) -> CircuitBreaker:
        breaker = self._breakers.get(domain)
        if breaker is None:
            breaker = CircuitBreaker(
                failure_threshold=self.failure_threshold,
                cooldown_seconds=self.cooldown_seconds,
                clock=self.clock,
            )
            self._breakers[domain] = breaker
        return breaker
