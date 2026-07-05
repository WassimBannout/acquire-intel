"""Engine & session factory — the one place that opens DB connections.

The engine URL comes from the config boundary (``get_settings().database_url``),
never from ``os.environ`` directly (ADR-0008). ``get_engine`` is process-wide and
cached; ``session_scope`` gives a transactional session that commits on success and
rolls back on error.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from acquire_intel.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine (created once)."""
    settings = get_settings()
    return create_engine(settings.database_url, future=True, pool_pre_ping=True)


@lru_cache(maxsize=1)
def _get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def new_session() -> Session:
    """Create a new session bound to the process engine (caller manages its lifecycle)."""
    return _get_session_factory()()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session: commit on success, roll back on exception, always close."""
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
