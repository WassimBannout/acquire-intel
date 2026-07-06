"""Product read-endpoint integration tests (T1.6, FR-13, specs/openapi.yaml).

Drives the Flask test client against live Postgres and asserts the two read routes are
spec-conformant: camelCase shape, ``Money.amount`` as a string, per-response freshness
(``dataAsOf`` + ``stale``), per-observation ``capturedAt`` + ``sourceId``, ``latestPrice``/
``inStock`` derived from the latest observation, window filtering, and the 404 path.

Data is committed and the tables truncated around each test (the request runs in the app's own
``session_scope``, so it must read committed state). Skips when no DB is configured/reachable.
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
_SOURCE_ID = "demo_rest"
_STALE_AFTER = 21_600  # 6h freshness budget for the seeded source
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
    """A committing session on a clean slate; tables truncated before and after."""
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


def _seed_source(session: Session, *, stale_after: int = _STALE_AFTER) -> None:
    SourceRepository(session).add(
        Source(
            id=_SOURCE_ID,
            kind="rest",
            base_url="https://shop.example.com",
            stale_after_seconds=stale_after,
            crawl_policy={},
        )
    )
    session.commit()


def _seed_product(
    session: Session,
    *,
    external_id: str,
    title: str,
    price: str,
    captured_at: datetime,
    run_id: str,
    in_stock: bool = True,
) -> str:
    """Persist one product + observation via the repositories; return its canonical id."""
    runs = CrawlRunRepository(session)
    if runs.get(run_id) is None:
        runs.open(run_id=run_id, source_id=_SOURCE_ID, started_at=captured_at)
    raw = RawProduct(
        external_id=external_id,
        title=title,
        url=f"https://shop.example.com/products/{external_id}",
        raw_price=price,
        currency=None,
        in_stock=in_stock,
    )
    item = normalize(
        raw,
        source_id=_SOURCE_ID,
        run_id=run_id,
        captured_at=captured_at,
        default_currency="USD",
    )
    ProductRepository(session).upsert(item.product)
    PriceObservationRepository(session).append(item.observation)
    session.commit()
    return item.product.id


# --- GET /products -----------------------------------------------------------------------


def test_list_products_shape_and_freshness(app: Flask, session: Session) -> None:
    _seed_source(session)
    now = datetime.now(UTC)
    _seed_product(
        session,
        external_id="7001",
        title="Trail Runner",
        price="129.95",
        captured_at=now,
        run_id="run-1",
    )

    resp = app.test_client().get(f"{BASE}/products")
    assert resp.status_code == 200
    body = resp.get_json()

    # Freshness envelope present and fresh (just captured).
    assert "dataAsOf" in body
    assert body["stale"] is False

    [product] = body["data"]
    assert product["id"] == "demo_rest:7001"
    assert product["sourceId"] == "demo_rest"
    assert product["title"] == "Trail Runner"
    assert product["url"].endswith("/7001")
    # latestPrice derived from the latest observation, amount as a *string*.
    assert product["latestPrice"] == {"amount": "129.95", "currency": "USD"}
    assert product["inStock"] is True
    assert "lastSeenAt" in product


def test_list_products_latest_price_is_most_recent_observation(
    app: Flask, session: Session
) -> None:
    _seed_source(session)
    early = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    late = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
    _seed_product(
        session,
        external_id="7001",
        title="Trail Runner",
        price="129.95",
        captured_at=early,
        run_id="run-1",
    )
    _seed_product(
        session,
        external_id="7001",
        title="Trail Runner",
        price="119.95",
        captured_at=late,
        run_id="run-2",
    )

    body = app.test_client().get(f"{BASE}/products").get_json()
    [product] = body["data"]
    assert product["latestPrice"]["amount"] == "119.95"


def test_list_products_filter_and_search(app: Flask, session: Session) -> None:
    _seed_source(session)
    now = datetime.now(UTC)
    _seed_product(
        session,
        external_id="1",
        title="Trail Runner",
        price="10.00",
        captured_at=now,
        run_id="run-1",
    )
    _seed_product(
        session,
        external_id="2",
        title="Road Cruiser",
        price="20.00",
        captured_at=now,
        run_id="run-1",
    )

    client = app.test_client()
    titles = {p["title"] for p in client.get(f"{BASE}/products?q=trail").get_json()["data"]}
    assert titles == {"Trail Runner"}

    empty = client.get(f"{BASE}/products?source=nope").get_json()["data"]
    assert empty == []


def test_list_products_marks_stale_data(app: Flask, session: Session) -> None:
    _seed_source(session, stale_after=3600)  # 1h budget
    old = datetime.now(UTC) - timedelta(hours=48)
    _seed_product(
        session,
        external_id="7001",
        title="Old One",
        price="9.99",
        captured_at=old,
        run_id="run-old",
    )

    body = app.test_client().get(f"{BASE}/products").get_json()
    assert body["stale"] is True


def test_list_products_empty_is_fresh(app: Flask, session: Session) -> None:
    _seed_source(session)
    body = app.test_client().get(f"{BASE}/products").get_json()
    assert body["data"] == []
    assert body["stale"] is False
    assert "dataAsOf" in body


# --- GET /products/{id}/price-history ----------------------------------------------------


def test_price_history_shape(app: Flask, session: Session) -> None:
    _seed_source(session)
    early = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    late = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)
    _seed_product(
        session,
        external_id="7001",
        title="Trail Runner",
        price="129.95",
        captured_at=early,
        run_id="run-1",
    )
    _seed_product(
        session,
        external_id="7001",
        title="Trail Runner",
        price="119.95",
        captured_at=late,
        run_id="run-2",
    )

    body = (
        app.test_client().get(f"{BASE}/products/demo_rest:7001/price-history?window=all").get_json()
    )

    assert body["productId"] == "demo_rest:7001"
    assert "dataAsOf" in body
    assert "stale" in body
    # Oldest-first, each point carries capturedAt + sourceId + Money price.
    amounts = [o["price"]["amount"] for o in body["observations"]]
    assert amounts == ["129.95", "119.95"]
    first = body["observations"][0]
    assert first["sourceId"] == "demo_rest"
    assert "capturedAt" in first
    assert first["price"]["currency"] == "USD"


def test_price_history_window_filters_old_points(app: Flask, session: Session) -> None:
    _seed_source(session)
    now = datetime.now(UTC)
    _seed_product(
        session,
        external_id="7001",
        title="Trail Runner",
        price="200.00",
        captured_at=now - timedelta(days=200),
        run_id="run-old",
    )
    _seed_product(
        session,
        external_id="7001",
        title="Trail Runner",
        price="150.00",
        captured_at=now,
        run_id="run-new",
    )

    body = (
        app.test_client().get(f"{BASE}/products/demo_rest:7001/price-history?window=90d").get_json()
    )
    amounts = [o["price"]["amount"] for o in body["observations"]]
    assert amounts == ["150.00"]  # the 200-day-old point is outside the 90d window


def test_price_history_unknown_product_is_404_problem_json(app: Flask, session: Session) -> None:
    _seed_source(session)
    resp = app.test_client().get(f"{BASE}/products/demo_rest:missing/price-history")
    assert resp.status_code == 404
    assert resp.mimetype == "application/problem+json"
    assert resp.get_json()["status"] == 404


def test_price_history_invalid_window_is_400(app: Flask, session: Session) -> None:
    _seed_source(session)
    _seed_product(
        session,
        external_id="7001",
        title="Trail Runner",
        price="10.00",
        captured_at=datetime.now(UTC),
        run_id="run-1",
    )
    resp = app.test_client().get(f"{BASE}/products/demo_rest:7001/price-history?window=bogus")
    assert resp.status_code == 400
    assert resp.mimetype == "application/problem+json"
