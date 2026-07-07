"""Repositories — the persistence API over the ORM models (T0.3 + T1.5, ADR-0006).

Boundaries encoded here (docs/03):
- ``price_observations`` is **append-only** — :class:`PriceObservationRepository` exposes
  ``append`` and reads, never an update or delete.
- ``products`` is a rebuildable **upsert projection** — :meth:`ProductRepository.upsert`
  inserts-or-updates on the canonical id and preserves ``first_seen_at``.
- ``crawl_runs`` is the collection **ledger** — :class:`CrawlRunRepository` opens a run
  (``running``) and closes it with a terminal status + item counts.

Repositories take the canonical pydantic contracts (``acquire_intel.contracts``) and map to
the ORM; they never depend on the acquisition/pipeline layers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from acquire_intel.storage.models import BanEvent, CrawlRun, PriceObservation, Product, Source

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal
    from typing import Any

    from sqlalchemy.orm import Session

    from acquire_intel import contracts
    from acquire_intel.contracts import RunStatus


class SourceRepository:
    """CRUD-lite access to the ``sources`` registry."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, source: Source) -> Source:
        """Persist a new source (flushed so the row is visible within the transaction)."""
        self._session.add(source)
        self._session.flush()
        return source

    def get(self, source_id: str) -> Source | None:
        """Return the source by id, or ``None`` if it does not exist."""
        return self._session.get(Source, source_id)

    def list_ids(self) -> list[str]:
        """Return all registered source ids (ordered) — handy for the crawl registry."""
        return list(self._session.scalars(select(Source.id).order_by(Source.id)))

    def stale_after_for(self, source_ids: set[str]) -> dict[str, int]:
        """Return ``{source_id: stale_after_seconds}`` for the given sources (freshness)."""
        if not source_ids:
            return {}
        rows = self._session.execute(
            select(Source.id, Source.stale_after_seconds).where(Source.id.in_(source_ids))
        )
        return {row.id: row.stale_after_seconds for row in rows}


class ProductRepository:
    """Upsert access to the ``products`` projection (rebuildable, one row per canonical id)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, product: contracts.Product) -> None:
        """Insert or update the projection for ``product.id``.

        On conflict the descriptive fields and ``last_seen_at`` are refreshed while
        ``first_seen_at`` is preserved (``last_seen_at`` only ever moves forward). The
        derived ``latest_price``/``in_stock`` are not stored here — they come from the latest
        observation at query time (docs/03 §2.2).
        """
        stmt = pg_insert(Product).values(
            id=product.id,
            source_id=product.source_id,
            external_id=product.external_id,
            title=product.title,
            brand=product.brand,
            url=product.url,
            image_url=product.image_url,
            first_seen_at=product.first_seen_at,
            last_seen_at=product.last_seen_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Product.id],
            set_={
                "title": stmt.excluded.title,
                "brand": stmt.excluded.brand,
                "url": stmt.excluded.url,
                "image_url": stmt.excluded.image_url,
                "last_seen_at": func.greatest(Product.last_seen_at, stmt.excluded.last_seen_at),
            },
        )
        self._session.execute(stmt)

    def get(self, product_id: str) -> Product | None:
        """Return the projection row by canonical id, or ``None``."""
        return self._session.get(Product, product_id)

    def get_many(self, product_ids: list[str]) -> dict[str, Product]:
        """Return the projection rows for ``product_ids`` keyed by id (missing ids omitted)."""
        if not product_ids:
            return {}
        rows = self._session.scalars(select(Product).where(Product.id.in_(product_ids)))
        return {row.id: row for row in rows}

    def list(
        self, *, source: str | None = None, q: str | None = None, limit: int = 24
    ) -> list[Product]:
        """Return products (latest-seen first) for the read surface.

        ``source`` filters by source id; ``q`` is a case-insensitive title substring search;
        ``limit`` caps the result (the caller is responsible for clamping to the spec bounds).
        """
        stmt = select(Product)
        if source is not None:
            stmt = stmt.where(Product.source_id == source)
        if q is not None:
            stmt = stmt.where(Product.title.ilike(f"%{q}%"))
        stmt = stmt.order_by(Product.last_seen_at.desc(), Product.id).limit(limit)
        return list(self._session.scalars(stmt))

    def count(self) -> int:
        """Total number of product rows (test/health helper)."""
        return self._session.scalar(select(func.count()).select_from(Product)) or 0


class PriceObservationRepository:
    """Append-only access to the ``price_observations`` time-series."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, observation: contracts.PriceObservation) -> PriceObservation:
        """Insert one immutable observation; flushed so its generated id is available."""
        row = PriceObservation(
            product_id=observation.product_id,
            source_id=observation.source_id,
            run_id=observation.run_id,
            amount=observation.amount,
            currency=observation.currency,
            in_stock=observation.in_stock,
            captured_at=observation.captured_at,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def list_for(self, product_id: str, *, since: datetime | None = None) -> list[PriceObservation]:
        """Return a product's observations, oldest-first (the price-history axis).

        ``since`` (inclusive) trims the series to a time window; ``None`` returns all.
        """
        stmt = select(PriceObservation).where(PriceObservation.product_id == product_id)
        if since is not None:
            stmt = stmt.where(PriceObservation.captured_at >= since)
        return list(self._session.scalars(stmt.order_by(PriceObservation.captured_at)))

    def latest_for_many(self, product_ids: list[str]) -> dict[str, PriceObservation]:
        """Return the newest observation per product id (for the list projection).

        Uses Postgres ``DISTINCT ON`` — one row per product, the latest by ``captured_at``.
        """
        if not product_ids:
            return {}
        rows = self._session.scalars(
            select(PriceObservation)
            .where(PriceObservation.product_id.in_(product_ids))
            .order_by(PriceObservation.product_id, PriceObservation.captured_at.desc())
            .distinct(PriceObservation.product_id)
        )
        return {obs.product_id: obs for obs in rows}

    def history_since(
        self, *, source: str | None, since: datetime | None
    ) -> dict[str, list[PriceObservation]]:
        """Observations grouped by product id (chronological), for deal detection (T4.1).

        ``source`` filters by source id; ``since`` (inclusive) trims to the lookback window.
        """
        stmt = select(PriceObservation)
        if source is not None:
            stmt = stmt.where(PriceObservation.source_id == source)
        if since is not None:
            stmt = stmt.where(PriceObservation.captured_at >= since)
        stmt = stmt.order_by(PriceObservation.product_id, PriceObservation.captured_at)
        grouped: dict[str, list[PriceObservation]] = {}
        for row in self._session.scalars(stmt):
            grouped.setdefault(row.product_id, []).append(row)
        return grouped

    def latest_amounts_for_source(self, source_id: str) -> dict[str, Decimal]:
        """Latest committed price per product for a source (for the continuity gate, T3.5).

        One row per product, the newest by ``captured_at`` (``DISTINCT ON``); used to preload
        prior prices so a per-product jump can be judged without a query per item.
        """
        rows = self._session.execute(
            select(PriceObservation.product_id, PriceObservation.amount)
            .where(PriceObservation.source_id == source_id)
            .order_by(PriceObservation.product_id, PriceObservation.captured_at.desc())
            .distinct(PriceObservation.product_id)
        ).all()
        return {row.product_id: row.amount for row in rows}

    def count_for(self, product_id: str) -> int:
        """Number of observations recorded for a product."""
        return (
            self._session.scalar(
                select(func.count())
                .select_from(PriceObservation)
                .where(PriceObservation.product_id == product_id)
            )
            or 0
        )


class CrawlRunRepository:
    """The crawl-run ledger: open a run, then close it with a terminal status + counts."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def open(self, *, run_id: str, source_id: str, started_at: datetime) -> CrawlRun:
        """Record a new run in ``running`` state; flushed so downstream FKs resolve."""
        run = CrawlRun(
            id=run_id,
            source_id=source_id,
            status="running",
            items_ok=0,
            items_rejected=0,
            ban_events=0,
            timings={},
            started_at=started_at,
        )
        self._session.add(run)
        self._session.flush()
        return run

    def close(
        self,
        run_id: str,
        *,
        status: RunStatus,
        items_ok: int,
        items_rejected: int,
        finished_at: datetime,
        ban_events: int = 0,
        timings: dict[str, Any] | None = None,
    ) -> None:
        """Finalize a run: set its terminal status, item counts, and finish time."""
        run = self._session.get(CrawlRun, run_id)
        if run is None:
            raise KeyError(f"unknown crawl run: {run_id}")
        run.status = status
        run.items_ok = items_ok
        run.items_rejected = items_rejected
        run.ban_events = ban_events
        run.finished_at = finished_at
        if timings is not None:
            run.timings = timings
        self._session.flush()

    def baseline_count(self, source_id: str, *, exclude_run_id: str) -> int | None:
        """The most recent **committed** run's item count for a source (volume-gate baseline).

        Considers only runs that actually committed data (``success``/``partial``) — a
        ``failed``/``quarantined`` run committed nothing, so its count is not a baseline. Returns
        ``None`` when the source has no committed history yet.
        """
        return self._session.scalar(
            select(CrawlRun.items_ok)
            .where(
                CrawlRun.source_id == source_id,
                CrawlRun.id != exclude_run_id,
                CrawlRun.status.in_(("success", "partial")),
                CrawlRun.finished_at.is_not(None),
            )
            .order_by(CrawlRun.finished_at.desc())
            .limit(1)
        )

    def get(self, run_id: str) -> CrawlRun | None:
        """Return the run by id, or ``None``."""
        return self._session.get(CrawlRun, run_id)


class BanEventRepository:
    """The anti-bot audit trail — append-only ``ban_events`` rows for a run (T3.6, docs/03 §2.4)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, run_id: str, events: list[contracts.BanEvent]) -> int:
        """Append the run's detected ban events; returns how many were written."""
        for event in events:
            self._session.add(
                BanEvent(
                    run_id=run_id,
                    kind=event.kind,
                    http_status=event.http_status,
                    action_taken=event.action_taken,
                    occurred_at=event.occurred_at,
                )
            )
        self._session.flush()
        return len(events)

    def list_for(self, run_id: str) -> list[BanEvent]:
        """Return a run's ban events, oldest-first (the audit order)."""
        return list(
            self._session.scalars(
                select(BanEvent).where(BanEvent.run_id == run_id).order_by(BanEvent.occurred_at)
            )
        )
