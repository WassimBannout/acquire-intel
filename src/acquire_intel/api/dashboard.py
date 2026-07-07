"""Server-rendered dashboard: price-history charts + a crawler-health panel (T4.3, ADR-0007).

A light Jinja + Chart.js surface over the read layer (docs/07 §5), mounted at the site root (the
JSON API lives under ``API_BASE_PATH``). Two views:

* ``GET /`` — the overview: a **crawler-health panel** (per source: last run status, freshness,
  items ok/rejected, ban count, identity/proxy rotations, a ban-events sparkline) plus the
  collected products with their latest price.
* ``GET /products/<id>`` — a product page whose price chart is fed client-side from the existing
  ``/products/{id}/price-history`` JSON endpoint (no duplicate serialization).

Routes stay thin: query repositories → build view models (crawler health via the pure
:mod:`acquire_intel.analytics.health`) → render. No business logic in templates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from flask import Blueprint, render_template

from acquire_intel.analytics.health import RunPoint, SourceHealth, summarize_source
from acquire_intel.api.products import _is_stale
from acquire_intel.config import get_settings
from acquire_intel.storage import (
    BanEventRepository,
    CrawlRunRepository,
    PriceObservationRepository,
    ProductRepository,
    SourceRepository,
    session_scope,
)

if TYPE_CHECKING:
    from acquire_intel.storage import CrawlRun, PriceObservation, Product

dashboard_bp = Blueprint("dashboard", __name__)

# Rotation-shaped ban actions (recovery activity surfaced on the panel, docs/07 §4).
_ROTATION_ACTIONS = ("rotate_identity", "rotate_proxy")
_RECENT_RUNS = 10  # health window per source
_PRODUCT_LIMIT = 60  # products shown on the overview


def _health_panel(
    sources: SourceRepository,
    runs: CrawlRunRepository,
    bans: BanEventRepository,
    *,
    now: datetime,
) -> list[SourceHealth]:
    """Build the per-source crawler-health views from the ledgers."""
    thresholds = sources.stale_after_for(set(sources.list_ids()))
    panel: list[SourceHealth] = []
    for source_id in sources.list_ids():
        recent: list[CrawlRun] = runs.recent(source_id, limit=_RECENT_RUNS)
        actions = bans.counts_by_action([r.id for r in recent])
        rotations = sum(actions.get(a, 0) for a in _ROTATION_ACTIONS)
        points = [
            RunPoint(
                status=r.status,
                started_at=r.started_at,
                finished_at=r.finished_at,
                items_ok=r.items_ok,
                items_rejected=r.items_rejected,
                ban_events=r.ban_events,
            )
            for r in recent
        ]
        panel.append(
            summarize_source(
                source_id,
                points,
                rotations=rotations,
                stale_after_seconds=thresholds.get(source_id),
                now=now,
            )
        )
    return panel


@dashboard_bp.get("/")
def overview() -> str:
    """Render the crawler-health panel + the collected-products table."""
    now = datetime.now(UTC)
    with session_scope() as session:
        health = _health_panel(
            SourceRepository(session),
            CrawlRunRepository(session),
            BanEventRepository(session),
            now=now,
        )
        products: list[Product] = ProductRepository(session).list(limit=_PRODUCT_LIMIT)
        latest = PriceObservationRepository(session).latest_for_many([p.id for p in products])
        rows = [(p, latest.get(p.id)) for p in products]
        data_as_of = max((p.last_seen_at for p in products), default=None)
        stale = any(h.stale for h in health)
    return render_template(
        "dashboard.html",
        health=health,
        rows=rows,
        data_as_of=data_as_of,
        stale=stale,
    )


@dashboard_bp.get("/products/<product_id>")
def product_detail(product_id: str) -> tuple[str, int] | str:
    """Render a product's price-history chart (data fetched from the JSON API client-side)."""
    now = datetime.now(UTC)
    with session_scope() as session:
        product: Product | None = ProductRepository(session).get(product_id)
        if product is None:
            return render_template("not_found.html", product_id=product_id), 404
        latest: PriceObservation | None = (
            PriceObservationRepository(session).latest_for_many([product_id]).get(product_id)
        )
        source = SourceRepository(session).get(product.source_id)
        threshold = source.stale_after_seconds if source is not None else None
        stale = _is_stale(product.last_seen_at, threshold, now=now)
    return render_template(
        "product.html",
        product=product,
        latest=latest,
        stale=stale,
        api_base_path=get_settings().api_base_path,
    )
