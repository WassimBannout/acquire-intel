"""Exponential backoff with jitter (T3.3, ADR-0005, docs/04 §2.4).

Pure delay maths, so the "how long to wait before retrying" decision is deterministic and
unit-testable with a seeded RNG — no reactor, no sleeping. The Scrapy wiring (retrying a 429/503
after this delay) lives in :mod:`.middleware`.

We use **full jitter** (``uniform(0, cap)``) over a capped exponential (``base·2^attempt``), the
AWS-blessed scheme that spreads retries out and avoids thundering herds. A server ``Retry-After``
directive is honoured as a *floor*: we never retry sooner than the server asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from random import Random


@dataclass(frozen=True)
class BackoffPolicy:
    """Bounds for retry backoff (from source/app config)."""

    base_delay: float = 0.5  # seconds; the first retry's exponential base
    max_delay: float = 30.0  # seconds; hard cap on any single wait
    max_retries: int = 3  # attempts before giving up (then the ban gate records + drops)


def exponential_cap(attempt: int, *, base_delay: float, max_delay: float) -> float:
    """The (un-jittered) delay ceiling for a 0-indexed ``attempt``: ``min(max, base·2^attempt)``."""
    if attempt < 0:
        raise ValueError("attempt must be >= 0")
    return min(max_delay, base_delay * (2.0**attempt))


def compute_delay(
    attempt: int,
    *,
    policy: BackoffPolicy,
    retry_after: float | None,
    rng: Random,
) -> float:
    """Seconds to wait before retry ``attempt`` (0-indexed). Deterministic for a given ``rng``.

    Full jitter over the exponential cap, with a ``Retry-After`` floor (never sooner than the
    server asked), the whole thing clamped to ``policy.max_delay``.
    """
    cap = exponential_cap(attempt, base_delay=policy.base_delay, max_delay=policy.max_delay)
    delay = rng.uniform(0.0, cap)
    if retry_after is not None and retry_after > 0:
        delay = max(delay, min(retry_after, policy.max_delay))
    return min(delay, policy.max_delay)
