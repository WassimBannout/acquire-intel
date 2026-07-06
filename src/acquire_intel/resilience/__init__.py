"""resilience: the anti-bot resilience layer.

Proxy rotation, identity/fingerprint rotation, adaptive throttling, backoff/retry,
circuit-breaking, and ban detection (ADR-0005, docs/04).
"""

from __future__ import annotations

from acquire_intel.resilience.classifier import (
    Classification,
    ban_kind,
    classify,
    is_ban,
    recommended_action,
)
from acquire_intel.resilience.middleware import STAT_BAN_EVENTS, BanDetectionMiddleware

__all__ = [
    "STAT_BAN_EVENTS",
    "BanDetectionMiddleware",
    "Classification",
    "ban_kind",
    "classify",
    "is_ban",
    "recommended_action",
]
