"""`GET /deals` integration tests (T4.1, FR-17, specs/openapi.yaml).

Drives the Flask test client against live Postgres: seeds each product's price history, then
asserts the endpoint ranks drops vs. a product's own recent high, is spec-conformant (camelCase,
string money, freshness envelope), and honours `source`/`limit`. Data is committed and truncated
around each test. Skips when no DB is configured/reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.api import create_app
from acquire_intel.config import ConfigError, get_settings
from acquire_intel.pipeline.normalize import normalize
from acquire_intel.storage import (
    CrawlRunRepository,
    PriceObservationRepository,
    ProductRepository,
    Source,
    SourceRepository,
    get_engine,
    new_session,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from flask import Flask
    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

BASE = "/api/v1"
_TABLES = "ban_events, price_observations, crawl_runs, products, sources"


@pytest.fixture(scope="module")
def engine() -> Engine:
    try:
        eng = get_engine()
        with eng.connect():
            pass
    except (ConfigError, OperationalError) as exc:  # pragma: no cover - env dependent
        pytest.skip(f"Postgres not available: {exc}")
    return eng


def _truncate(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    _truncate(engine)
    sess = new_session()
    try:
        yield sess
    finally:
        sess.close()
        _truncate(engine)


@pytest.fixture
def app(session: Session, monkeypatch: pytest.MonkeyPatch) -> Flask:
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("ADMIN_TOKEN", "test")
    get_settings.cache_clear()
    return create_app()


def _seed_source(session: Session, source_id: str) -> None:
    SourceRepository(session).add(
        Source(
            id=source_id,
            kind="rest",
            base_url=f"https://{source_id}.example.com",
            stale_after_seconds=21_600,
            crawl_policy={},
        )
    )
    session.commit()


def _observe(
    session: Session, *, source_id: str, external_id: str, price: str, captured_at: datetime
) -> None:
    """Append one observation (upserting the product) at a point in time."""
    runs = CrawlRunRepository(session)
    run_id = f"run-{captured_at.isoformat()}"
    if runs.get(run_id) is None:
        runs.open(run_id=run_id, source_id=source_id, started_at=captured_at)
    raw = RawProduct(
        external_id=external_id,
        title=f"Product {external_id}",
        url=f"https://{source_id}.example.com/p/{external_id}",
        raw_price=price,
        currency="USD",
    )
    item = normalize(
        raw, source_id=source_id, run_id=run_id, captured_at=captured_at, default_currency="USD"
    )
    ProductRepository(session).upsert(item.product)
    PriceObservationRepository(session).append(item.observation)
    session.commit()


def test_deals_ranks_drops_with_freshness(app: Flask, session: Session) -> None:
    _seed_source(session, "demo_rest")
    now = datetime.now(UTC)
    old = now - timedelta(days=10)
    # A: 100 → 70 (30% drop). B: 200 → 100 (50% drop). C: stable 50 (no deal).
    _observe(session, source_id="demo_rest", external_id="A", price="100", captured_at=old)
    _observe(session, source_id="demo_rest", external_id="A", price="70", captured_at=now)
    _observe(session, source_id="demo_rest", external_id="B", price="200", captured_at=old)
    _observe(session, source_id="demo_rest", external_id="B", price="100", captured_at=now)
    _observe(session, source_id="demo_rest", external_id="C", price="50", captured_at=old)
    _observe(session, source_id="demo_rest", external_id="C", price="50", captured_at=now)

    resp = app.test_client().get(f"{BASE}/deals")
    assert resp.status_code == 200
    body = resp.get_json()

    assert "dataAsOf" in body and body["stale"] is False
    # Ranked by drop magnitude; the stable product C is not a deal.
    assert [d["product"]["id"] for d in body["data"]] == ["demo_rest:B", "demo_rest:A"]

    big = body["data"][0]
    assert big["dropPct"] == 50.0
    assert big["previousPrice"] == {"amount": "200", "currency": "USD"}
    assert big["currentPrice"] == {"amount": "100", "currency": "USD"}
    assert big["product"]["latestPrice"] == {"amount": "100", "currency": "USD"}
    assert "since" in big


def test_deals_respects_limit_and_source_filter(app: Flask, session: Session) -> None:
    _seed_source(session, "demo_rest")
    _seed_source(session, "other")
    now = datetime.now(UTC)
    old = now - timedelta(days=5)
    _observe(session, source_id="demo_rest", external_id="A", price="100", captured_at=old)
    _observe(session, source_id="demo_rest", external_id="A", price="70", captured_at=now)
    _observe(session, source_id="other", external_id="Z", price="100", captured_at=old)
    _observe(session, source_id="other", external_id="Z", price="40", captured_at=now)

    # limit caps the result to the single biggest drop across all sources (other:Z, 60%).
    limited = app.test_client().get(f"{BASE}/deals?limit=1").get_json()
    assert [d["product"]["id"] for d in limited["data"]] == ["other:Z"]

    # source filter restricts to one source.
    filtered = app.test_client().get(f"{BASE}/deals?source=demo_rest").get_json()
    assert [d["product"]["id"] for d in filtered["data"]] == ["demo_rest:A"]


def test_deals_empty_when_nothing_dropped(app: Flask, session: Session) -> None:
    _seed_source(session, "demo_rest")
    now = datetime.now(UTC)
    old = now - timedelta(days=3)
    # Price rose — never a deal.
    _observe(session, source_id="demo_rest", external_id="A", price="50", captured_at=old)
    _observe(session, source_id="demo_rest", external_id="A", price="80", captured_at=now)

    body = app.test_client().get(f"{BASE}/deals").get_json()
    assert body["data"] == []
