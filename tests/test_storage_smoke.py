"""Storage baseline smoke test (T0.3, ADR-0006).

Proves the round trip: connect to the compose Postgres → write a ``Source`` via the
repository → read it back. Runs inside a transaction that is rolled back, so it
leaves no residue. Skips cleanly when no DB is configured/reachable, keeping the
unit-only ``pytest`` run green without infrastructure (CI provides the DB).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from acquire_intel.config import ConfigError
from acquire_intel.storage import Source, SourceRepository, get_engine

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine() -> Engine:
    """Process engine, or skip the module if config/DB is unavailable."""
    try:
        eng = get_engine()
        with eng.connect():
            pass
    except (ConfigError, OperationalError) as exc:  # pragma: no cover - env dependent
        pytest.skip(f"Postgres not available: {exc}")
    return eng


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session on an outer transaction that is rolled back after the test."""
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection, expire_on_commit=False)
    try:
        yield sess
    finally:
        sess.close()
        transaction.rollback()
        connection.close()


def test_source_write_then_read(session: Session) -> None:
    repo = SourceRepository(session)

    repo.add(
        Source(
            id="demo_rest",
            kind="rest",
            base_url="https://demo.invalid/api",
            stale_after_seconds=3600,
            crawl_policy={"rate": 1.0, "robots": True},
        )
    )

    got = repo.get("demo_rest")
    assert got is not None
    assert got.kind == "rest"
    assert got.crawl_policy == {"rate": 1.0, "robots": True}
    assert repo.list_ids() == ["demo_rest"]


def test_get_unknown_source_returns_none(session: Session) -> None:
    assert SourceRepository(session).get("does_not_exist") is None
