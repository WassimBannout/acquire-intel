"""Repositories — the persistence API over the ORM models.

T0.3 ships a minimal :class:`SourceRepository` to prove the storage baseline
end-to-end (write + read a row). Richer repositories (product upsert, observation
append, crawl-run ledger) arrive with T1.5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from acquire_intel.storage.models import Source

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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
