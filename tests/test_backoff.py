"""Pure backoff-maths tests (T3.3, docs/04 §2.4).

Deterministic with a seeded RNG: exact values, jitter bounds, exponential growth of the cap,
the ``max_delay`` clamp, and the ``Retry-After`` floor.
"""

from __future__ import annotations

from random import Random

import pytest

from acquire_intel.resilience.backoff import BackoffPolicy, compute_delay, exponential_cap

_POLICY = BackoffPolicy(base_delay=0.5, max_delay=30.0, max_retries=3)


def test_exponential_cap_doubles_until_clamped() -> None:
    assert exponential_cap(0, base_delay=0.5, max_delay=30.0) == 0.5
    assert exponential_cap(1, base_delay=0.5, max_delay=30.0) == 1.0
    assert exponential_cap(2, base_delay=0.5, max_delay=30.0) == 2.0
    assert exponential_cap(10, base_delay=0.5, max_delay=30.0) == 30.0  # clamped


def test_exponential_cap_rejects_negative_attempt() -> None:
    with pytest.raises(ValueError, match="attempt"):
        exponential_cap(-1, base_delay=0.5, max_delay=30.0)


@pytest.mark.parametrize("attempt", range(6))
def test_full_jitter_stays_within_the_cap(attempt: int) -> None:
    rng = Random(1234)
    cap = exponential_cap(attempt, base_delay=_POLICY.base_delay, max_delay=_POLICY.max_delay)
    for _ in range(200):
        delay = compute_delay(attempt, policy=_POLICY, retry_after=None, rng=rng)
        assert 0.0 <= delay <= cap


def test_delay_is_deterministic_for_a_seed() -> None:
    a = compute_delay(2, policy=_POLICY, retry_after=None, rng=Random(42))
    b = compute_delay(2, policy=_POLICY, retry_after=None, rng=Random(42))
    assert a == b


def test_retry_after_is_a_floor() -> None:
    # Even with a tiny jittered exponential, we never retry sooner than the server asked.
    for _ in range(100):
        delay = compute_delay(0, policy=_POLICY, retry_after=5.0, rng=Random())
        assert delay >= 5.0


def test_retry_after_is_clamped_to_max_delay() -> None:
    delay = compute_delay(0, policy=_POLICY, retry_after=999.0, rng=Random())
    assert delay == _POLICY.max_delay


def test_never_exceeds_max_delay() -> None:
    policy = BackoffPolicy(base_delay=10.0, max_delay=12.0, max_retries=10)
    for attempt in range(8):
        for _ in range(50):
            delay = compute_delay(attempt, policy=policy, retry_after=None, rng=Random())
            assert delay <= 12.0
