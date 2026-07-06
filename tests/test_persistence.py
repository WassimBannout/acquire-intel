"""Persistence + crawl-run ledger integration tests (T1.5, ADR-0006, docs/03 §2).

Proves against the compose Postgres that:
- a crawl run is opened (``running``) and closed with a terminal status + item counts;
- ``products`` upserts (re-running the same product does not duplicate the row, preserves
  ``first_seen_at``, advances ``last_seen_at``);
- ``price_observations`` is append-only (a second run appends a second immutable row).

Skips cleanly when no DB is configured/reachable (CI provides Postgres).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.config import ConfigError
from acquire_intel.pipeline.normalize import NormalizedItem, normalize
from acquire_intel.storage import (
    CrawlRunRepository,
    PriceObservationRepository,
    ProductRepository,
    Source,
    SourceRepository,
    get_engine,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

pytestmark = pytest.mark.integration

_SOURCE_ID = "demo_rest"


@pytest.fixture(scope="module")
def engine() -> Engine:
    try:
        eng = get_engine()
        with eng.connect():
            pass
    except (ConfigError, OperationalError) as exc:  # pragma: no cover - env dependent
        pytest.skip(f"Postgres not available: {exc}")
    return eng


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session on an outer transaction rolled back after the test (no residue)."""
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection, expire_on_commit=False)
    try:
        yield sess
    finally:
        sess.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def seeded_source(session: Session) -> str:
    """Insert the source row the product/run FKs depend on."""
    SourceRepository(session).add(
        Source(
            id=_SOURCE_ID,
            kind="rest",
            base_url="https://shop.example.com",
            stale_after_seconds=21600,
            crawl_policy={},
        )
    )
    return _SOURCE_ID


def _item(price: str, captured_at: datetime) -> NormalizedItem:
    raw = RawProduct(
        external_id="7001",
        title="Trail Runner 2000",
        url="https://shop.example.com/products/trail-runner-2000",
        raw_price=price,
        currency=None,
        in_stock=True,
    )
    return normalize(
        raw,
        source_id=_SOURCE_ID,
        run_id="ignored-here",  # the run id is set per-persist below
        captured_at=captured_at,
        default_currency="USD",
    )


def _persist(session: Session, item: NormalizedItem, run_id: str) -> None:
    ProductRepository(session).upsert(item.product)
    obs = item.observation.model_copy(update={"run_id": run_id})
    PriceObservationRepository(session).append(obs)


def test_open_and_close_crawl_run(session: Session, seeded_source: str) -> None:
    runs = CrawlRunRepository(session)
    started = datetime.now(UTC)

    opened = runs.open(run_id="run-1", source_id=seeded_source, started_at=started)
    assert opened.status == "running"

    runs.close(
        "run-1",
        status="success",
        items_ok=3,
        items_rejected=1,
        finished_at=started + timedelta(seconds=5),
    )
    stored = runs.get("run-1")
    assert stored is not None
    assert stored.status == "success"
    assert stored.items_ok == 3
    assert stored.items_rejected == 1
    assert stored.finished_at is not None


def test_product_upsert_and_observation_append_across_two_runs(
    session: Session, seeded_source: str
) -> None:
    products = ProductRepository(session)
    observations = PriceObservationRepository(session)
    runs = CrawlRunRepository(session)

    first_seen = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    later = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)

    # --- Run 1: first capture ---
    runs.open(run_id="run-1", source_id=seeded_source, started_at=first_seen)
    _persist(session, _item("129.95", first_seen), "run-1")
    runs.close("run-1", status="success", items_ok=1, items_rejected=0, finished_at=first_seen)

    product = products.get("demo_rest:7001")
    assert product is not None
    assert product.first_seen_at == first_seen
    assert observations.count_for("demo_rest:7001") == 1

    # --- Run 2: same product, new price, later capture ---
    runs.open(run_id="run-2", source_id=seeded_source, started_at=later)
    _persist(session, _item("119.95", later), "run-2")
    runs.close("run-2", status="success", items_ok=1, items_rejected=0, finished_at=later)

    # The upsert ran as a Core INSERT…ON CONFLICT; expire the identity map so reads reflect
    # committed DB state (what a fresh reader/the API would see), not cached ORM instances.
    session.expire_all()

    # Upsert: still one product row; first_seen preserved, last_seen advanced.
    assert products.count() == 1
    refreshed = products.get("demo_rest:7001")
    assert refreshed is not None
    assert refreshed.first_seen_at == first_seen
    assert refreshed.last_seen_at == later

    # Append-only: two immutable observations, oldest-first, distinct prices + runs.
    history = observations.list_for("demo_rest:7001")
    assert [o.amount for o in history] == [Decimal("129.95"), Decimal("119.95")]
    assert [o.run_id for o in history] == ["run-1", "run-2"]
    assert observations.count_for("demo_rest:7001") == 2


def test_observation_money_roundtrips_as_decimal(session: Session, seeded_source: str) -> None:
    runs = CrawlRunRepository(session)
    now = datetime.now(UTC)
    runs.open(run_id="run-1", source_id=seeded_source, started_at=now)
    _persist(session, _item("19.99", now), "run-1")

    [obs] = PriceObservationRepository(session).list_for("demo_rest:7001")
    assert isinstance(obs.amount, Decimal)
    assert obs.amount == Decimal("19.99")
    assert obs.currency == "USD"
