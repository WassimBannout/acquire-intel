"""Unit tests for the pure deal-detection math (T4.1, ADR-0013).

Deterministic boundaries for `compute_deal` / `rank_deals` — no DB, no Flask. The endpoint
wiring is covered by `test_deals_api.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from acquire_intel.analytics.deals import PricePoint, compute_deal, rank_deals

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _p(amount: str, *, days: int, in_stock: bool | None = None) -> PricePoint:
    return PricePoint(
        amount=Decimal(amount), currency="USD", at=_T0 + timedelta(days=days), in_stock=in_stock
    )


# --- compute_deal ----------------------------------------------------------------------------


def test_a_drop_from_the_recent_high_is_a_deal() -> None:
    # High 100 (day 0), latest 70 (day 2) → 30% drop.
    deal = compute_deal("s:1", [_p("100", days=0), _p("70", days=2)], min_drop_pct=10.0)
    assert deal is not None
    assert deal.previous_amount == Decimal("100")
    assert deal.current_amount == Decimal("70")
    assert deal.drop_pct == 30.0
    assert deal.since == _T0  # when it was at the high
    assert deal.current_at == _T0 + timedelta(days=2)


def test_a_drop_below_the_threshold_is_not_a_deal() -> None:
    # 100 → 95 is only 5%, under the 10% floor.
    assert compute_deal("s:1", [_p("100", days=0), _p("95", days=1)], min_drop_pct=10.0) is None


def test_exactly_the_threshold_is_a_deal() -> None:
    deal = compute_deal("s:1", [_p("100", days=0), _p("90", days=1)], min_drop_pct=10.0)
    assert deal is not None and deal.drop_pct == 10.0


def test_a_price_at_its_high_is_not_a_deal() -> None:
    # Latest is the maximum (price rose) → no drop.
    assert compute_deal("s:1", [_p("50", days=0), _p("80", days=1)], min_drop_pct=10.0) is None


def test_single_or_empty_history_is_not_a_deal() -> None:
    assert compute_deal("s:1", [_p("50", days=0)], min_drop_pct=10.0) is None
    assert compute_deal("s:1", [], min_drop_pct=10.0) is None


def test_rebound_from_a_low_still_measures_against_the_high() -> None:
    # 100 (day0) → 40 (day1) → 60 (day2, latest): a deal vs the 100 high, 40% off.
    deal = compute_deal(
        "s:1", [_p("100", days=0), _p("40", days=1), _p("60", days=2)], min_drop_pct=10.0
    )
    assert deal is not None and deal.drop_pct == 40.0 and deal.since == _T0


def test_since_picks_the_most_recent_time_at_the_high() -> None:
    # The 100 high occurs on day 0 and again day 3; the latest is day 4 at 80.
    deal = compute_deal(
        "s:1",
        [_p("100", days=0), _p("100", days=3), _p("80", days=4)],
        min_drop_pct=10.0,
    )
    assert deal is not None and deal.since == _T0 + timedelta(days=3)


# --- rank_deals ------------------------------------------------------------------------------


def test_rank_orders_by_drop_magnitude_and_caps_at_limit() -> None:
    histories = {
        "s:small": [_p("100", days=0), _p("85", days=1)],  # 15%
        "s:big": [_p("100", days=0), _p("50", days=1)],  # 50%
        "s:none": [_p("100", days=0), _p("99", days=1)],  # 1% — filtered out
    }
    ranked = rank_deals(histories, min_drop_pct=10.0, limit=10)
    assert [d.product_id for d in ranked] == ["s:big", "s:small"]  # biggest first, non-deal dropped

    top = rank_deals(histories, min_drop_pct=10.0, limit=1)
    assert [d.product_id for d in top] == ["s:big"]


def test_rank_ties_break_by_product_id_for_determinism() -> None:
    histories = {
        "s:bbb": [_p("100", days=0), _p("70", days=1)],  # 30%
        "s:aaa": [_p("100", days=0), _p("70", days=1)],  # 30%
    }
    ranked = rank_deals(histories, min_drop_pct=10.0, limit=10)
    assert [d.product_id for d in ranked] == ["s:aaa", "s:bbb"]
