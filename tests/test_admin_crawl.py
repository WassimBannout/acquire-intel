"""``POST /admin/crawl`` tests (T4.5, docs/08 §4, specs/openapi.yaml triggerCrawl).

Drives the Flask client against live Postgres with the crawl *launch* stubbed (monkeypatched
``orchestrator._spawn_crawl``) so no real Scrapy subprocess runs: asserts token gating (401),
rate-limiting (429), the 202 body + that a ``running`` ledger row is recorded, source targeting,
and the unknown-source 404. Skips when no DB is configured/reachable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from acquire_intel.api import create_app
from acquire_intel.config import ConfigError, get_settings
from acquire_intel.storage import (
    CrawlRunRepository,
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
TOKEN = "s3cr3t-admin"
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
def spawns(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Record crawl launches instead of spawning a real subprocess."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "acquire_intel.acquisition.orchestrator._spawn_crawl",
        lambda source_id, run_id: calls.append((source_id, run_id)),
    )
    return calls


def _make_app(monkeypatch: pytest.MonkeyPatch, *, rate_limit: int = 60) -> Flask:
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("ADMIN_RATE_LIMIT_PER_MINUTE", str(rate_limit))
    get_settings.cache_clear()
    return create_app()


@pytest.fixture
def app(session: Session, monkeypatch: pytest.MonkeyPatch) -> Flask:
    return _make_app(monkeypatch)


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def test_requires_admin_token(app: Flask, spawns: list[tuple[str, str]]) -> None:
    # No header → 401; wrong token → 401; nothing launched.
    assert app.test_client().post(f"{BASE}/admin/crawl").status_code == 401
    resp = app.test_client().post(f"{BASE}/admin/crawl", headers=_auth("wrong"))
    assert resp.status_code == 401
    assert resp.mimetype == "application/problem+json"
    assert spawns == []


def test_triggers_all_registered_sources(
    app: Flask, session: Session, spawns: list[tuple[str, str]]
) -> None:
    _seed_source(session, "demo_rest")
    _seed_source(session, "demo_graphql")

    resp = app.test_client().post(f"{BASE}/admin/crawl", headers=_auth())
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["accepted"] is True
    launched = {r["source"] for r in body["runs"]}
    assert launched == {"demo_rest", "demo_graphql"}
    assert all(r["status"] == "running" for r in body["runs"])
    assert {s for s, _ in spawns} == {"demo_rest", "demo_graphql"}

    # A running ledger row was recorded for each launched run (recorded run).
    reader = new_session()
    try:
        runs = CrawlRunRepository(reader)
        for r in body["runs"]:
            row = runs.get(r["id"])
            assert row is not None
            assert row.status == "running"
    finally:
        reader.close()


def test_triggers_named_source_only(
    app: Flask, session: Session, spawns: list[tuple[str, str]]
) -> None:
    _seed_source(session, "demo_rest")
    _seed_source(session, "demo_graphql")

    resp = app.test_client().post(
        f"{BASE}/admin/crawl", headers=_auth(), json={"source": "demo_rest"}
    )
    assert resp.status_code == 202
    assert [r["source"] for r in resp.get_json()["runs"]] == ["demo_rest"]
    assert [s for s, _ in spawns] == ["demo_rest"]


def test_unknown_source_is_404(app: Flask, session: Session, spawns: list[tuple[str, str]]) -> None:
    _seed_source(session, "demo_rest")
    resp = app.test_client().post(f"{BASE}/admin/crawl", headers=_auth(), json={"source": "nope"})
    assert resp.status_code == 404
    assert resp.mimetype == "application/problem+json"
    assert spawns == []  # nothing launched when a target is invalid


def test_rate_limited_after_budget(
    session: Session, monkeypatch: pytest.MonkeyPatch, spawns: list[tuple[str, str]]
) -> None:
    app = _make_app(monkeypatch, rate_limit=1)
    _seed_source(session, "demo_rest")
    client = app.test_client()
    assert client.post(f"{BASE}/admin/crawl", headers=_auth()).status_code == 202
    resp = client.post(f"{BASE}/admin/crawl", headers=_auth())
    assert resp.status_code == 429
    assert resp.mimetype == "application/problem+json"
