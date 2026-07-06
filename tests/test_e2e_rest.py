"""End-to-end REST slice — the M1 gate (T1.7).

Proves the whole vertical slice against live Postgres: ``acquire-intel crawl demo_rest`` (run as
a real CLI subprocess) fetches a paginated ``products.json`` from a local fixture server →
pipeline (validate/normalize/dedup) → persists ``products`` + ``price_observations`` and records
the ``crawl_runs`` ledger → the Flask API serves the observations with freshness.

Deterministic: no live site — the fixture server serves ``tests/fixtures/demo_rest`` (ADR-0009
spirit; the full adversarial harness is M3). Skips cleanly when Postgres is unreachable.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from acquire_intel.api import create_app
from acquire_intel.config import ConfigError, get_settings
from acquire_intel.storage import (
    CrawlRun,
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
_TABLES = "ban_events, price_observations, crawl_runs, products, sources"
_FIXTURE = Path(__file__).parent / "fixtures" / "demo_rest" / "valid_payload.json"


# --- local fixture server (Shopify-style paginated products.json) ------------------------


class _FixtureHandler(BaseHTTPRequestHandler):
    payload = _FIXTURE.read_bytes()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/products.json"):
            self.send_response(404)
            self.end_headers()
            return
        page = int(parse_qs(parsed.query).get("page", ["1"])[0])
        body = self.payload if page == 1 else b'{"products": []}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # keep test output clean
        pass


@pytest.fixture
def fixture_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


# --- database plumbing -------------------------------------------------------------------


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


def _register_source(session: Session, base_url: str) -> None:
    """Seed the ``sources`` registry row the runner reads for base_url + currency."""
    SourceRepository(session).add(
        Source(
            id=_SOURCE_ID,
            kind="rest",
            base_url=base_url,
            stale_after_seconds=21_600,
            crawl_policy={"default_currency": "USD"},
        )
    )
    session.commit()


def _run_crawl_cli() -> subprocess.CompletedProcess[str]:
    """Run ``acquire-intel crawl demo_rest`` as a real subprocess (fresh reactor)."""
    env = {
        **os.environ,
        "FLASK_SECRET_KEY": "test",
        "ADMIN_TOKEN": "test",
        "ROBOTSTXT_OBEY": "false",  # local fixture server we own
        "AUTOTHROTTLE_ENABLED": "false",
        "DEFAULT_DOWNLOAD_DELAY": "0",
    }
    return subprocess.run(
        [sys.executable, "-m", "acquire_intel.cli", "crawl", _SOURCE_ID],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


# --- the gate ----------------------------------------------------------------------------


def test_crawl_to_api_end_to_end(app: Flask, session: Session, fixture_server: str) -> None:
    _register_source(session, fixture_server)

    result = _run_crawl_cli()
    assert result.returncode == 0, result.stderr

    # --- data landed in Postgres --------------------------------------------------------
    reader = new_session()
    try:
        products = ProductRepository(reader)
        observations = PriceObservationRepository(reader)
        # Two valid products (the no-price item 7003 is skipped, never fabricated).
        assert products.count() == 2
        assert products.get("demo_rest:7001") is not None
        assert products.get("demo_rest:7003") is None
        assert observations.count_for("demo_rest:7001") == 1
        assert observations.count_for("demo_rest:7002") == 1

        # The run is recorded in the ledger with a terminal status + item count.
        run = reader.scalars(select(CrawlRun).where(CrawlRun.source_id == _SOURCE_ID)).one()
        assert run.status in {"success", "partial"}
        assert run.finished_at is not None
        assert run.items_ok == 2
    finally:
        reader.close()

    # --- API serves it with freshness ---------------------------------------------------
    client = app.test_client()

    listing = client.get(f"{BASE}/products").get_json()
    assert "dataAsOf" in listing
    assert listing["stale"] is False
    by_id = {p["id"]: p for p in listing["data"]}
    assert set(by_id) == {"demo_rest:7001", "demo_rest:7002"}
    assert by_id["demo_rest:7001"]["latestPrice"] == {"amount": "129.95", "currency": "USD"}
    assert by_id["demo_rest:7001"]["sourceId"] == "demo_rest"

    history = client.get(f"{BASE}/products/demo_rest:7001/price-history?window=all").get_json()
    assert history["productId"] == "demo_rest:7001"
    assert "dataAsOf" in history
    [point] = history["observations"]
    assert point["price"] == {"amount": "129.95", "currency": "USD"}
    assert point["sourceId"] == "demo_rest"
    assert "capturedAt" in point
