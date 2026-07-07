"""resilience: the anti-bot resilience layer.

Proxy rotation, identity/fingerprint rotation, adaptive throttling, backoff/retry,
circuit-breaking, and ban detection (ADR-0005, docs/04).
"""

from __future__ import annotations

from acquire_intel.resilience.backoff import BackoffPolicy, compute_delay
from acquire_intel.resilience.circuit import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitState,
)
from acquire_intel.resilience.classifier import (
    Classification,
    ban_kind,
    classify,
    is_ban,
    recommended_action,
)
from acquire_intel.resilience.identity import (
    BrowserProfile,
    Identity,
    IdentityPool,
)
from acquire_intel.resilience.middleware import (
    STAT_BAN_EVENTS,
    BackoffRetryMiddleware,
    BanDetectionMiddleware,
    CircuitBreakerMiddleware,
    IdentityRotationMiddleware,
)
from acquire_intel.resilience.proxy import ProxyHealth, ProxyPool

__all__ = [
    "STAT_BAN_EVENTS",
    "BackoffPolicy",
    "BackoffRetryMiddleware",
    "BanDetectionMiddleware",
    "BrowserProfile",
    "CircuitBreaker",
    "CircuitBreakerMiddleware",
    "CircuitBreakerRegistry",
    "CircuitState",
    "Classification",
    "Identity",
    "IdentityPool",
    "IdentityRotationMiddleware",
    "ProxyHealth",
    "ProxyPool",
    "ban_kind",
    "classify",
    "compute_delay",
    "is_ban",
    "recommended_action",
]
