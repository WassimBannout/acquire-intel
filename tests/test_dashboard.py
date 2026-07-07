"""Dashboard tests (T4.3, docs/07 §5, ADR-0007).

Two layers:

* **Pure** unit tests for :func:`acquire_intel.analytics.health.summarize_source` — freshness,
  rotations, trend, and empty history, no DB.
* **View** integration tests driving the Flask test client against live Postgres: the overview
  renders the crawler-health panel + product table (and their empty states), and the product page
  renders the chart scaffold or a 404 page. Skips when no DB is configured/reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from acquire_intel import contracts
from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.analytics.health import RunPoint, summarize_source
from acquire_intel.api import create_app
from acquire_intel.config import ConfigError, get_settings
from acquire_intel.pipeline.normalize import normalize
from acquire_intel.storage import (
    BanEventRepository,
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

BASE = "/api/v1"
_TABLES = "ban_events, price_observations, crawl_runs, products, sources"


# --------------------------------------------------------------------------- pure


def _run(status: str, *, at: datetime, ok: int = 0, rejected: int = 0, bans: int = 0) -> RunPoint:
    return RunPoint(
        status=status,
        started_at=at,
        finished_at=at,
        items_ok=ok,
        items_rejected=rejected,
        ban_events=bans,
    )


def test_summarize_empty_history() -> None:
    h = summarize_source("s", [], rotations=0, stale_after_seconds=3600, now=datetime.now(UTC))
    assert h.last_status is None
    assert h.stale is False  # nothing to be stale about yet
    assert h.trend == []
    assert h.total_runs == 0


def test_summarize_fresh_success() -> None:
    now = datetime.now(UTC)
    runs = [_run("success", at=now - timedelta(minutes=5), ok=12, bans=1)]
    h = summarize_source("s", runs, rotations=2, stale_after_seconds=3600, now=now)
    assert h.last_status == "success"
    assert h.items_ok == 12
    assert h.rotations == 2
    assert h.stale is False
    assert h.last_success_at is not None


def test_summarize_stale_when_last_success_old() -> None:
    now = datetime.now(UTC)
    runs = [_run("success", at=now - timedelta(hours=5), ok=3)]
    h = summarize_source("s", runs, rotations=0, stale_after_seconds=3600, now=now)
    assert h.stale is True


def test_summarize_stale_when_runs_never_committed() -> None:
    now = datetime.now(UTC)
    # Latest is a failed run; there is no successful run to be fresh from.
    runs = [_run("failed", at=now, bans=3), _run("failed", at=now - timedelta(minutes=1), bans=2)]
    h = summarize_source("s", runs, rotations=1, stale_after_seconds=3600, now=now)
    assert h.last_success_at is None
    assert h.stale is True
    # Trend is oldest→newest: the older run (2 bans) precedes the newest (3 bans).
    assert h.trend == [2, 3]


def test_summarize_no_stale_budget_never_stale() -> None:
    now = datetime.now(UTC)
    runs = [_run("failed", at=now - timedelta(days=30))]
    h = summarize_source("s", runs, rotations=0, stale_after_seconds=None, now=now)
    assert h.stale is False


# ----------------------------------------------------------------------- view (DB)

pytestmark_integration = pytest.mark.integration


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
) -> str:
    """Append one observation (opening a run + upserting the product); returns the run id."""
    runs = CrawlRunRepository(session)
    run_id = f"run-{source_id}-{captured_at.isoformat()}"
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
    return run_id


pytestmark = pytestmark_integration


def test_overview_empty_state(app: Flask) -> None:
    resp = app.test_client().get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "No sources registered yet" in html
    assert "No products collected yet" in html


def test_overview_renders_health_and_products(app: Flask, session: Session) -> None:
    _seed_source(session, "demo_rest")
    now = datetime.now(UTC)
    run_id = _observe(session, source_id="demo_rest", external_id="A", price="42", captured_at=now)
    # Close the run as a success with a ban that triggered an identity rotation.
    runs = CrawlRunRepository(session)
    runs.close(
        run_id,
        status="success",
        items_ok=1,
        items_rejected=0,
        finished_at=now,
        ban_events=1,
    )
    BanEventRepository(session).record(
        run_id,
        [
            contracts.BanEvent(
                kind="blocked",
                action_taken="rotate_identity",
                http_status=403,
                occurred_at=now,
            )
        ],
    )
    session.commit()

    html = app.test_client().get("/").get_data(as_text=True)
    # Health panel: the source, its status, and the rotation count are surfaced.
    assert "demo_rest" in html
    assert "success" in html
    assert "rotations" in html
    # Product table: the product title + latest price + a link to its detail page.
    assert "Product A" in html
    assert "42 USD" in html
    assert "/products/demo_rest:A" in html


def test_product_detail_renders_chart_scaffold(app: Flask, session: Session) -> None:
    _seed_source(session, "demo_rest")
    now = datetime.now(UTC)
    _observe(session, source_id="demo_rest", external_id="A", price="42", captured_at=now)

    resp = app.test_client().get("/products/demo_rest:A")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "price-chart" in html  # the canvas
    assert "Product A" in html
    # The chart is fed by the JSON API, not re-serialized server-side.
    assert f"{BASE}/products/demo_rest:A/price-history" in html


def test_product_detail_unknown_renders_404_page(app: Flask) -> None:
    resp = app.test_client().get("/products/nope:nope")
    assert resp.status_code == 404
    assert "Product not found" in resp.get_data(as_text=True)
