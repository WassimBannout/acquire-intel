"""Deals endpoint: ``GET /deals`` — products with the largest recent price drops (T4.1, FR-17).

Thin route: parse ``source``/``limit``, pull each product's windowed history, rank drops via the
pure :mod:`acquire_intel.analytics.deals`, and serialize through the camelCase API models with the
shared freshness envelope. Deals are relative to a product's **own** history (ADR-0013), never a
cross-product comparison.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from acquire_intel.analytics.deals import PricePoint, rank_deals
from acquire_intel.api.errors import ProblemError
from acquire_intel.api.products import _is_stale  # the shared freshness rule (docs/07)
from acquire_intel.api.serializers import DealOut, DealsResponse, MoneyOut, ProductOut
from acquire_intel.config import get_settings
from acquire_intel.storage import (
    PriceObservationRepository,
    ProductRepository,
    SourceRepository,
    session_scope,
)

if TYPE_CHECKING:
    from flask import Response

deals_bp = Blueprint("deals", __name__)

_DEFAULT_LIMIT = 20
_MIN_LIMIT = 1
_MAX_LIMIT = 50


def _parse_limit(raw: str | None) -> int:
    """Parse + clamp ``limit`` to the spec bounds (1-50, default 20)."""
    if raw is None:
        return _DEFAULT_LIMIT
    try:
        value = int(raw)
    except ValueError:
        raise ProblemError(400, "Invalid limit", "limit must be an integer") from None
    return max(_MIN_LIMIT, min(_MAX_LIMIT, value))


@deals_bp.get("/deals")
def list_deals() -> Response:
    """Rank products by how far their latest price sits below their recent high, with freshness."""
    source = request.args.get("source") or None
    limit = _parse_limit(request.args.get("limit"))
    cfg = get_settings()
    now = datetime.now(UTC)
    since = now - timedelta(days=cfg.deal_window_days)

    with session_scope() as session:
        histories = {
            product_id: [
                PricePoint(
                    amount=o.amount, currency=o.currency, at=o.captured_at, in_stock=o.in_stock
                )
                for o in observations
            ]
            for product_id, observations in PriceObservationRepository(session)
            .history_since(source=source, since=since)
            .items()
        }
        results = rank_deals(histories, min_drop_pct=cfg.deal_min_drop_pct, limit=limit)
        products = ProductRepository(session).get_many([d.product_id for d in results])
        thresholds = SourceRepository(session).stale_after_for(
            {products[d.product_id].source_id for d in results if d.product_id in products}
        )

        data = []
        for d in results:
            row = products.get(d.product_id)
            if row is None:  # projection missing (e.g. mid-retention) — skip, never fabricate
                continue
            current_price = MoneyOut(amount=str(d.current_amount), currency=d.current_currency)
            data.append(
                DealOut(
                    product=ProductOut(
                        id=row.id,
                        source_id=row.source_id,
                        title=row.title,
                        brand=row.brand,
                        url=row.url,
                        image_url=row.image_url,
                        latest_price=current_price,
                        in_stock=d.current_in_stock,
                        last_seen_at=row.last_seen_at,
                    ),
                    previous_price=MoneyOut(
                        amount=str(d.previous_amount), currency=d.previous_currency
                    ),
                    current_price=current_price,
                    drop_pct=d.drop_pct,
                    since=d.since,
                )
            )
        data_as_of = max((d.current_at for d in results), default=now)
        stale = _is_stale(data_as_of, max(thresholds.values(), default=None), now=now)
        payload = DealsResponse(data_as_of=data_as_of, stale=stale, data=data)

    return jsonify(payload.model_dump(by_alias=True, mode="json"))
