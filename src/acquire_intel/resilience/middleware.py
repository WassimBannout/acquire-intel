"""Ban-detection Scrapy downloader middleware (T3.2, ADR-0005, docs/04 §2.5).

Wraps the pure :func:`~acquire_intel.resilience.classifier.classify` as a downloader middleware so
**every** response is labelled before it can reach a spider callback. A non-``ok`` response is
recorded as a ``BanEvent`` (Scrapy stats + a structured log, and appended to the spider's
``ban_events`` sink when present, for the crawl-run ledger in T3.6) and then **dropped** via
``IgnoreRequest`` — the extractor never sees a block/CAPTCHA/empty page, so nothing garbage is ever
parsed or persisted (ADR-0008).

This task performs *detection + gating* only. The recommended recovery action (backoff / rotate)
is recorded on the event as policy; actually executing it — retrying under backoff or a fresh
identity instead of dropping — is layered on in T3.3 (throttle/backoff) and T3.4 (rotation).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from random import Random
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from scrapy.exceptions import IgnoreRequest

from acquire_intel.contracts import BanEvent
from acquire_intel.monitoring.logging import get_logger
from acquire_intel.resilience.backoff import BackoffPolicy, compute_delay
from acquire_intel.resilience.circuit import CircuitBreakerRegistry, CircuitState
from acquire_intel.resilience.classifier import (
    Classification,
    ban_kind,
    classify,
    recommended_action,
)
from acquire_intel.resilience.identity import IdentityPool
from acquire_intel.resilience.proxy import ProxyPool

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from scrapy import Spider
    from scrapy.crawler import Crawler
    from scrapy.http import Request, Response
    from scrapy.statscollectors import StatsCollector

    from acquire_intel.resilience.identity import Identity

_log = get_logger("acquire_intel.resilience.ban")

STAT_BAN_EVENTS = "acquire/ban_events"
STAT_BACKOFF_RETRIES = "acquire/backoff_retries"
STAT_BACKOFF_EXHAUSTED = "acquire/backoff_exhausted"
STAT_CIRCUIT_TRIPPED = "acquire/circuit_tripped"
STAT_CIRCUIT_SKIPPED = "acquire/circuit_open_skipped"
STAT_IDENTITY_ROTATIONS = "acquire/identity_rotations"
STAT_COOKIE_RETRIES = "acquire/cookie_retries"
STAT_ROTATION_EXHAUSTED = "acquire/rotation_exhausted"

# Statuses we own the backoff for (429 rate-limit, 503 unavailable). Removed from the built-in
# retrier (scrapy_settings) so this middleware is the single, Retry-After-aware owner.
_RETRYABLE_STATUSES = frozenset({429, 503})

# Persistent-adversary classifications that count toward tripping a domain's breaker. Rate-limits
# are transient and handled by backoff, so they are deliberately excluded.
_CIRCUIT_FAILURES = frozenset(
    {Classification.BLOCKED, Classification.CAPTCHA, Classification.EMPTY}
)

# Persistent per-identity blocks that warrant escalating to a fresh identity + proxy and retrying
# (ADR-0011). Same set as the breaker's: a rate-limit is transient (backoff's job), a cookie wall is
# handled separately below (same-identity replay), so neither rotates.
_ROTATE_ON = _CIRCUIT_FAILURES

_META_BACKOFF_RETRIES = "backoff_retries"
_META_ROTATION_ATTEMPTS = "rotation_attempts"


def _stat_for(kind: str) -> str:
    return f"acquire/ban/{kind}"


def _domain(url: str) -> str:
    return urlparse(url).netloc


def _is_infra_request(request: Request) -> bool:
    """robots.txt (and similar infra fetches) must bypass the resilience recovery layer."""
    return bool(request.meta.get("dont_obey_robotstxt"))


class BanDetectionMiddleware:
    """Classify every response; record + drop the bans so only ``ok`` responses reach a spider."""

    def __init__(self, stats: StatsCollector | None = None) -> None:
        self.stats = stats

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> BanDetectionMiddleware:
        return cls(stats=crawler.stats)

    def process_response(self, request: Request, response: Response, spider: Spider) -> Response:
        # Never gate infrastructure fetches (e.g. robots.txt), only real crawl responses.
        if _is_infra_request(request):
            return response

        classification = classify(status=response.status, body=response.body)
        if classification is Classification.OK:
            return response

        self._record(classification, request=request, response=response, spider=spider)
        raise IgnoreRequest(f"ban:{classification.value} for {request.url}")

    def _record(
        self,
        classification: Classification,
        *,
        request: Request,
        response: Response,
        spider: Spider,
    ) -> None:
        event = BanEvent(
            kind=ban_kind(classification),
            action_taken=recommended_action(classification),
            http_status=response.status,
            occurred_at=datetime.now(UTC),
        )
        if self.stats is not None:
            self.stats.inc_value(STAT_BAN_EVENTS)
            self.stats.inc_value(_stat_for(event.kind))

        # Hand the full event to the crawl-run ledger sink if the spider exposes one (T3.6).
        sink = getattr(spider, "ban_events", None)
        if isinstance(sink, list):
            sink.append(event)

        _log.warning(
            "resilience.ban_detected",
            kind=event.kind,
            action=event.action_taken,
            http_status=event.http_status,
            url=request.url,
        )


@dataclass(frozen=True)
class _RetryPlan:
    """A decision to retry a request after ``delay`` seconds with the prepared ``request``."""

    delay: float
    request: Request


class BackoffRetryMiddleware:
    """Retry 429/503 with Retry-After-aware exponential backoff (T3.3, docs/04 §2.4).

    Placed above the ban gate, so a rate-limited/unavailable response is *recovered* (retried
    under backoff) rather than recorded as a terminal ban. Once retries are exhausted the response
    falls through to the ban gate, which records it and drops it. ``process_response`` is async so
    the wait is a real ``await`` on the asyncio reactor; the retry *decision* is a pure method so it
    is unit-testable without sleeping.
    """

    def __init__(
        self,
        policy: BackoffPolicy,
        *,
        stats: StatsCollector | None = None,
        rng: Random | None = None,
    ) -> None:
        self.policy = policy
        self.stats = stats
        self.rng = rng or Random()
        # Injection seam: tests swap in a no-op so the async path runs without real time.
        self._sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> BackoffRetryMiddleware:
        s = crawler.settings
        policy = BackoffPolicy(
            base_delay=s.getfloat("ACQUIRE_BACKOFF_BASE_DELAY", 0.5),
            max_delay=s.getfloat("ACQUIRE_BACKOFF_MAX_DELAY", 30.0),
            max_retries=s.getint("ACQUIRE_BACKOFF_MAX_RETRIES", 3),
        )
        return cls(policy, stats=crawler.stats)

    def plan_retry(self, request: Request, response: Response) -> _RetryPlan | None:
        """Decide whether/what to retry — pure, no sleeping. ``None`` means 'do not retry'."""
        if _is_infra_request(request) or response.status not in _RETRYABLE_STATUSES:
            return None
        attempt = int(request.meta.get(_META_BACKOFF_RETRIES, 0))
        if attempt >= self.policy.max_retries:
            if self.stats is not None:
                self.stats.inc_value(STAT_BACKOFF_EXHAUSTED)
            return None  # give up → falls through to the ban gate

        delay = compute_delay(
            attempt,
            policy=self.policy,
            retry_after=_parse_retry_after(response),
            rng=self.rng,
        )
        retry = request.copy()
        retry.dont_filter = True
        retry.meta[_META_BACKOFF_RETRIES] = attempt + 1
        return _RetryPlan(delay=delay, request=retry)

    async def process_response(
        self, request: Request, response: Response, spider: Spider
    ) -> Response | Request:
        plan = self.plan_retry(request, response)
        if plan is None:
            return response
        if self.stats is not None:
            self.stats.inc_value(STAT_BACKOFF_RETRIES)
        _log.info(
            "resilience.backoff_retry",
            url=request.url,
            status=response.status,
            delay=round(plan.delay, 3),
            attempt=plan.request.meta[_META_BACKOFF_RETRIES],
        )
        await self._sleep(plan.delay)
        return plan.request


class CircuitBreakerMiddleware:
    """Per-domain circuit breaker (T3.3, docs/04 §2.4).

    Counts blocks per domain; once a domain trips, its requests are short-circuited for a
    cool-down instead of hammering it, then a single probe is allowed to test recovery.
    """

    def __init__(
        self, registry: CircuitBreakerRegistry, *, stats: StatsCollector | None = None
    ) -> None:
        self.registry = registry
        self.stats = stats

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> CircuitBreakerMiddleware:
        s = crawler.settings
        registry = CircuitBreakerRegistry(
            failure_threshold=s.getint("ACQUIRE_CIRCUIT_FAILURE_THRESHOLD", 5),
            cooldown_seconds=s.getfloat("ACQUIRE_CIRCUIT_COOLDOWN_SECONDS", 60.0),
        )
        return cls(registry, stats=crawler.stats)

    def process_request(self, request: Request, spider: Spider) -> None:
        if _is_infra_request(request):
            return None
        breaker = self.registry.for_domain(_domain(request.url))
        if not breaker.allow():
            if self.stats is not None:
                self.stats.inc_value(STAT_CIRCUIT_SKIPPED)
            raise IgnoreRequest(f"circuit open for {_domain(request.url)}")
        return None

    def process_response(self, request: Request, response: Response, spider: Spider) -> Response:
        if _is_infra_request(request):
            return response
        breaker = self.registry.for_domain(_domain(request.url))
        classification = classify(status=response.status, body=response.body)
        if classification in _CIRCUIT_FAILURES:
            was_open = breaker.state is CircuitState.OPEN
            breaker.record_failure()
            if not was_open and breaker.state is CircuitState.OPEN:
                if self.stats is not None:
                    self.stats.inc_value(STAT_CIRCUIT_TRIPPED)
                _log.warning("resilience.circuit_tripped", domain=_domain(request.url))
        elif classification is Classification.OK:
            breaker.record_success()
        # rate_limited is transient (owned by BackoffRetryMiddleware) — no breaker change.
        return response


class IdentityRotationMiddleware:
    """Coherent identity + proxy rotation, escalating on a persistent block (T3.4, ADR-0011).

    Respectful by default: until a source actively blocks us, requests keep the honest **contact**
    ``USER_AGENT`` (docs/08) and no browser identity is stamped — only a pool proxy is attached when
    one is configured. Placed above the ban gate (priority 582): when a response is a *persistent*
    block (``blocked``/``captcha``/``empty``) we **escalate** — swap to a coherent browser identity
    (User-Agent + matching headers + a fresh per-identity cookie jar) plus a fresh proxy, and retry
    the request rather than let the ban gate drop it. The harness ``block_after_n`` scenario keys
    its budget on the identity, so a fresh identity resets it and the retry succeeds.

    A ``blocked`` response that carries a ``Set-Cookie`` (a cookie wall) is instead retried with the
    **same** identity so Scrapy's ``CookiesMiddleware`` replays the freshly-set session cookie —
    rotating would throw the cookie away. ``rate_limited`` never rotates (backoff owns it). Both
    recoveries are bounded by ``max_attempts`` per request; once exhausted the response falls
    through to the ban gate, which records + drops it.
    """

    def __init__(
        self,
        identities: IdentityPool,
        proxies: ProxyPool,
        *,
        max_attempts: int = 4,
        stats: StatsCollector | None = None,
    ) -> None:
        self.identities = identities
        self.proxies = proxies
        self.max_attempts = max_attempts
        self.stats = stats
        # We start on the honest contact UA; only a block escalates us into the browser catalogue.
        self._escalated = False
        self._proxy = proxies.acquire()

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> IdentityRotationMiddleware:
        s = crawler.settings
        proxies = ProxyPool(
            urls=s.getlist("ACQUIRE_PROXY_POOL"),
            cooldown_seconds=s.getfloat("ACQUIRE_PROXY_COOLDOWN_SECONDS", 60.0),
        )
        return cls(
            IdentityPool(),
            proxies,
            max_attempts=s.getint("ACQUIRE_ROTATION_MAX_ATTEMPTS", 4),
            stats=crawler.stats,
        )

    def process_request(self, request: Request, spider: Spider) -> None:
        if _is_infra_request(request):
            return None
        if self._escalated:
            identity = self.identities.current
            request.headers[b"User-Agent"] = identity.user_agent
            for name, value in identity.headers.items():
                request.headers[name] = value
            # Fresh jar per identity: a rotated bundle never carries the abandoned one's cookies.
            request.meta["cookiejar"] = identity.key
        if self._proxy is not None:
            request.meta["proxy"] = self._proxy
        return None

    def process_response(
        self, request: Request, response: Response, spider: Spider
    ) -> Response | Request:
        if _is_infra_request(request):
            return response
        classification = classify(status=response.status, body=response.body)
        if classification is Classification.OK:
            self.proxies.record_success(self._proxy)
            return response

        # Cookie wall: blocked, but the server just handed us a session cookie — retry the SAME
        # identity so CookiesMiddleware replays it (rotating would discard the cookie).
        if classification is Classification.BLOCKED and response.headers.get(b"Set-Cookie"):
            retry = self._bounded_retry(request, STAT_COOKIE_RETRIES)
            if retry is not None:
                _log.info("resilience.cookie_retry", url=request.url)
                return retry
            return response

        if classification in _ROTATE_ON:
            retry = self._bounded_retry(request, STAT_IDENTITY_ROTATIONS)
            if retry is not None:
                self.proxies.record_ban(self._proxy)
                identity = self._escalate()
                self._proxy = self.proxies.acquire()
                _log.info(
                    "resilience.identity_rotated",
                    url=request.url,
                    to_identity=identity.key,
                    kind=classification.value,
                )
                return retry
            if self.stats is not None:
                self.stats.inc_value(STAT_ROTATION_EXHAUSTED)
        return response

    def _escalate(self) -> Identity:
        """Adopt the first browser identity on the first block; advance the pool thereafter."""
        if not self._escalated:
            self._escalated = True
            return self.identities.current
        return self.identities.rotate()

    def _bounded_retry(self, request: Request, stat: str) -> Request | None:
        """Return a retry copy of ``request`` (counting ``stat``), or ``None`` once exhausted."""
        attempts = int(request.meta.get(_META_ROTATION_ATTEMPTS, 0))
        if attempts >= self.max_attempts:
            return None
        retry = request.copy()
        retry.dont_filter = True
        retry.meta[_META_ROTATION_ATTEMPTS] = attempts + 1
        if self.stats is not None:
            self.stats.inc_value(stat)
        return retry


def _parse_retry_after(response: Response) -> float | None:
    """Parse a numeric ``Retry-After`` (seconds) header; ignore the HTTP-date form."""
    raw = response.headers.get(b"Retry-After")
    if not raw:
        return None
    try:
        return float(raw.decode() if isinstance(raw, bytes) else raw)
    except (ValueError, AttributeError):
        return None
