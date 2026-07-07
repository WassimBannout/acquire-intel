"""Deal detection — significant price drops vs. a product's own history (T4.1, ADR-0013, FR-17).

A **deal** is a product whose latest price is at least ``min_drop_pct`` below its recent high
(the maximum price in a lookback window). This is deliberately *relative to the product's own
history* — never a cross-product comparison — so a genuinely cheap item isn't a "deal" and a
briefly-inflated one that merely returned to normal isn't either.

Pure and I/O-free: :func:`compute_deal` / :func:`rank_deals` operate on lightweight
:class:`PricePoint`s, so every threshold and tie-break is unit-testable without a DB. The API
route (``api/deals.py``) maps observation rows → ``PricePoint``s and ranks them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime
    from decimal import Decimal


@dataclass(frozen=True)
class PricePoint:
    """One price observation, reduced to what deal detection needs."""

    amount: Decimal
    currency: str
    at: datetime
    in_stock: bool | None = None


@dataclass(frozen=True)
class DealResult:
    """A detected price drop for one product (highest recent price → current price)."""

    product_id: str
    previous_amount: Decimal  # the recent high
    previous_currency: str
    current_amount: Decimal  # the latest price
    current_currency: str
    current_at: datetime  # when the latest price was captured (drives freshness)
    drop_pct: float  # (previous - current) / previous * 100, rounded
    since: datetime  # when the product was at its recent high
    current_in_stock: bool | None


def compute_deal(
    product_id: str, points: Sequence[PricePoint], *, min_drop_pct: float
) -> DealResult | None:
    """Return a :class:`DealResult` if the latest price is a big enough drop, else ``None``.

    ``current`` is the latest point by time; the reference high is the maximum amount in
    ``points`` (ties broken toward the most recent time at that high). No prior high, a
    non-positive reference, or a current price not below the high → not a deal.
    """
    if not points:
        return None
    current = max(points, key=lambda p: p.at)
    reference = max(points, key=lambda p: (p.amount, p.at))
    if reference.amount <= 0 or current.amount >= reference.amount:
        return None
    drop_pct = round(float((reference.amount - current.amount) / reference.amount * 100), 2)
    if drop_pct < min_drop_pct:
        return None
    return DealResult(
        product_id=product_id,
        previous_amount=reference.amount,
        previous_currency=reference.currency,
        current_amount=current.amount,
        current_currency=current.currency,
        current_at=current.at,
        drop_pct=drop_pct,
        since=reference.at,
        current_in_stock=current.in_stock,
    )


def rank_deals(
    histories: Mapping[str, Sequence[PricePoint]], *, min_drop_pct: float, limit: int
) -> list[DealResult]:
    """Compute deals per product, then rank by drop magnitude (largest first), capped at ``limit``.

    Ties in ``drop_pct`` break by ``product_id`` so the ordering is fully deterministic.
    """
    deals = [
        deal
        for product_id, points in histories.items()
        if (deal := compute_deal(product_id, points, min_drop_pct=min_drop_pct)) is not None
    ]
    deals.sort(key=lambda d: (-d.drop_pct, d.product_id))
    return deals[:limit]
