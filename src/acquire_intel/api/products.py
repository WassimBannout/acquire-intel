"""Product read endpoints: ``GET /products`` + ``GET /products/{id}/price-history`` (T1.6).

Routes stay thin — parse query params, call repositories, serialize through the API models
(``api/serializers.py``) with ``by_alias`` so the JSON matches ``specs/openapi.yaml``. Every
response carries freshness (``dataAsOf`` + ``stale``); each observation carries ``capturedAt``
+ ``sourceId``. ``latestPrice``/``inStock`` are derived from the latest observation at query
time (docs/03 §2.2). Unknown products yield a 404 problem+json (FR-13, docs/07).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from acquire_intel.api.errors import ProblemError
from acquire_intel.api.serializers import (
    MoneyOut,
    PriceHistoryResponse,
    PriceObservationOut,
    ProductOut,
    ProductsResponse,
)
from acquire_intel.storage import (
    PriceObservationRepository,
    ProductRepository,
    SourceRepository,
    session_scope,
)

if TYPE_CHECKING:
    from flask import Response

    from acquire_intel.storage import PriceObservation, Product

products_bp = Blueprint("products", __name__)

_DEFAULT_LIMIT = 24
_MIN_LIMIT = 1
_MAX_LIMIT = 100

# price-history windows → lookback in days (``all`` = unbounded); default per openapi.
_WINDOW_DAYS: dict[str, int | None] = {
    "30d": 30,
    "90d": 90,
    "180d": 180,
    "365d": 365,
    "all": None,
}
_DEFAULT_WINDOW = "90d"


def _parse_limit(raw: str | None) -> int:
    """Parse + clamp ``limit`` to the spec bounds (1-100, default 24)."""
    if raw is None:
        return _DEFAULT_LIMIT
    try:
        value = int(raw)
    except ValueError:
        raise ProblemError(400, "Invalid limit", "limit must be an integer") from None
    return max(_MIN_LIMIT, min(_MAX_LIMIT, value))


def _window_since(raw: str, now: datetime) -> datetime | None:
    """Resolve a ``window`` value to an inclusive lower bound (``None`` = all)."""
    if raw not in _WINDOW_DAYS:
        allowed = ", ".join(_WINDOW_DAYS)
        raise ProblemError(400, "Invalid window", f"window must be one of: {allowed}")
    days = _WINDOW_DAYS[raw]
    return None if days is None else now - timedelta(days=days)


def _is_stale(data_as_of: datetime, stale_after_seconds: int | None, *, now: datetime) -> bool:
    """Freshness rule (docs/07): data older than the source's ``stale_after`` budget."""
    if stale_after_seconds is None:
        return False
    return (now - data_as_of).total_seconds() > stale_after_seconds


def _product_out(row: Product, latest: PriceObservation | None) -> ProductOut:
    """Map a projection row (+ its latest observation) to the API product shape."""
    latest_price = None
    in_stock = None
    if latest is not None:
        latest_price = MoneyOut(amount=str(latest.amount), currency=latest.currency)
        in_stock = latest.in_stock
    return ProductOut(
        id=row.id,
        source_id=row.source_id,
        title=row.title,
        brand=row.brand,
        url=row.url,
        image_url=row.image_url,
        latest_price=latest_price,
        in_stock=in_stock,
        last_seen_at=row.last_seen_at,
    )


def _observation_out(obs: PriceObservation) -> PriceObservationOut:
    """Map an observation row to the API price-point shape."""
    return PriceObservationOut(
        captured_at=obs.captured_at,
        source_id=obs.source_id,
        price=MoneyOut(amount=str(obs.amount), currency=obs.currency),
        in_stock=obs.in_stock,
    )


@products_bp.get("/products")
def list_products() -> Response:
    """List collected products (latest state) with freshness."""
    source = request.args.get("source") or None
    q = request.args.get("q") or None
    limit = _parse_limit(request.args.get("limit"))
    now = datetime.now(UTC)

    with session_scope() as session:
        rows = ProductRepository(session).list(source=source, q=q, limit=limit)
        latest = PriceObservationRepository(session).latest_for_many([r.id for r in rows])
        thresholds = SourceRepository(session).stale_after_for({r.source_id for r in rows})
        data = [_product_out(r, latest.get(r.id)) for r in rows]
        data_as_of = max((r.last_seen_at for r in rows), default=now)
        stale = _is_stale(data_as_of, max(thresholds.values(), default=None), now=now)
        payload = ProductsResponse(data_as_of=data_as_of, stale=stale, data=data)

    return jsonify(payload.model_dump(by_alias=True, mode="json"))


@products_bp.get("/products/<product_id>/price-history")
def price_history(product_id: str) -> Response:
    """Return the append-only price series for one product, or 404 if unknown."""
    now = datetime.now(UTC)
    since = _window_since(request.args.get("window", _DEFAULT_WINDOW), now)

    with session_scope() as session:
        product = ProductRepository(session).get(product_id)
        if product is None:
            raise ProblemError(404, "Product not found", f"No product with id {product_id!r}")
        observations = PriceObservationRepository(session).list_for(product_id, since=since)
        source = SourceRepository(session).get(product.source_id)
        threshold = source.stale_after_seconds if source is not None else None
        points = [_observation_out(o) for o in observations]
        data_as_of = max((o.captured_at for o in observations), default=product.last_seen_at)
        stale = _is_stale(data_as_of, threshold, now=now)
        payload = PriceHistoryResponse(
            data_as_of=data_as_of, stale=stale, product_id=product_id, observations=points
        )

    return jsonify(payload.model_dump(by_alias=True, mode="json"))
