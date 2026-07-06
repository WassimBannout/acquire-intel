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

from acquire_intel.storage.models import CrawlRun, PriceObservation, Product, Source

if TYPE_CHECKING:
    from datetime import datetime
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

    def list_for(self, product_id: str) -> list[PriceObservation]:
        """Return a product's observations, oldest-first (the price-history axis)."""
        return list(
            self._session.scalars(
                select(PriceObservation)
                .where(PriceObservation.product_id == product_id)
                .order_by(PriceObservation.captured_at)
            )
        )

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

    def get(self, run_id: str) -> CrawlRun | None:
        """Return the run by id, or ``None``."""
        return self._session.get(CrawlRun, run_id)
