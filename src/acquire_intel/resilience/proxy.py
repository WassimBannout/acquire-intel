"""Proxy pool manager (T3.4, ADR-0005/0011, docs/04 §2.1).

A pure, health-tracking rotation over an env-supplied proxy pool. Each proxy carries a running
success/failure tally; a proxy that gets banned is **quarantined** for a cool-down and skipped
until it elapses. Picks round-robin among the currently healthy proxies.

The pool is intentionally happy with **zero** proxies: an empty pool means "connect directly",
which is exactly right for local runs and the adversarial harness (docs/04 §2.1) — proxies are
never hardcoded, only supplied via config/env. When every proxy is cooling down we also fall back
to a direct connection rather than fail the crawl.

Pure and clock-injectable (no Scrapy, no sockets), so quarantine + recovery are deterministically
testable. The Scrapy wiring (stamping ``request.meta["proxy"]``, reporting ban/success) lives in
:mod:`.middleware`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


@dataclass
class ProxyHealth:
    """Per-proxy health: success/failure tallies and an optional quarantine deadline."""

    url: str
    successes: int = 0
    failures: int = 0
    banned_until: float | None = None

    def success_rate(self) -> float:
        """Fraction of attributed responses that succeeded (1.0 before any observation)."""
        total = self.successes + self.failures
        return 1.0 if total == 0 else self.successes / total


@dataclass
class ProxyPool:
    """Round-robin over healthy proxies, quarantining banned ones for a cool-down.

    An empty ``urls`` list is valid and means *direct connection*: :meth:`acquire` returns
    ``None``. ``clock`` returns monotonic seconds (injected in tests).
    """

    urls: Sequence[str] = ()
    cooldown_seconds: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _health: dict[str, ProxyHealth] = field(init=False)
    _cursor: int = 0

    def __post_init__(self) -> None:
        # Preserve order, drop blanks/dupes — the pool comes straight from a config string.
        seen: dict[str, None] = {}
        for url in self.urls:
            cleaned = url.strip()
            if cleaned and cleaned not in seen:
                seen[cleaned] = None
        self._ordered = list(seen)
        self._health = {url: ProxyHealth(url=url) for url in self._ordered}

    def _is_healthy(self, url: str) -> bool:
        banned_until = self._health[url].banned_until
        if banned_until is None:
            return True
        if self.clock() >= banned_until:
            self._health[url].banned_until = None  # quarantine elapsed → back in rotation
            return True
        return False

    def acquire(self) -> str | None:
        """Return the next healthy proxy URL, or ``None`` for a direct connection.

        ``None`` is returned when the pool is empty *or* every proxy is currently quarantined —
        degrading to a direct connection beats failing the crawl.
        """
        if not self._ordered:
            return None
        n = len(self._ordered)
        for offset in range(n):
            url = self._ordered[(self._cursor + offset) % n]
            if self._is_healthy(url):
                self._cursor = (self._cursor + offset + 1) % n
                return url
        return None  # all quarantined → direct

    def record_success(self, url: str | None) -> None:
        """Attribute a good response to ``url`` (no-op for a direct connection)."""
        health = self._health.get(url) if url is not None else None
        if health is not None:
            health.successes += 1

    def record_ban(self, url: str | None) -> None:
        """Quarantine ``url`` for the cool-down and count the failure (no-op for direct)."""
        health = self._health.get(url) if url is not None else None
        if health is not None:
            health.failures += 1
            health.banned_until = self.clock() + self.cooldown_seconds

    def health(self) -> list[ProxyHealth]:
        """A snapshot of per-proxy health (for the ``proxy_health`` metric, docs/07)."""
        return list(self._health.values())
