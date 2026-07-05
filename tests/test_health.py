"""Flask health + problem+json tests (T0.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from acquire_intel.api import create_app
from acquire_intel.config import get_settings
from acquire_intel.storage.db import get_engine

if TYPE_CHECKING:
    from collections.abc import Iterator

    from flask import Flask

BASE = "/api/v1"
COMPOSE_DB = "postgresql+psycopg://acquire:acquire@localhost:5544/acquire"
DEAD_DB = "postgresql+psycopg://u:p@localhost:5999/none"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Base required env; each test overrides DATABASE_URL and resets caches."""
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("ADMIN_TOKEN", "test")
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


def _app_with_db(monkeypatch: pytest.MonkeyPatch, url: str) -> Flask:
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    return create_app()


def test_health_ok_when_db_reachable(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app_with_db(monkeypatch, COMPOSE_DB)
    # Skip if the compose DB isn't up (keeps unit-only runs green).
    with app.test_client() as client:
        resp = client.get(f"{BASE}/health")
        if resp.status_code == 503:
            pytest.skip("compose Postgres not reachable")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"


def test_health_503_when_db_unreachable(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app_with_db(monkeypatch, DEAD_DB)
    resp = app.test_client().get(f"{BASE}/health")
    assert resp.status_code == 503
    assert resp.get_json()["checks"]["database"] == "unreachable"


def test_unhandled_error_returns_problem_json(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app_with_db(monkeypatch, DEAD_DB)

    @app.get("/boom")
    def _boom() -> str:  # pragma: no cover - body never returns
        raise RuntimeError("kaboom")

    resp = app.test_client().get("/boom")
    assert resp.status_code == 500
    assert resp.mimetype == "application/problem+json"
    body = resp.get_json()
    assert body["title"] == "Internal Server Error"
    assert body["status"] == 500
    assert "kaboom" not in (body.get("detail") or "")  # internals not leaked


def test_unknown_route_returns_problem_json(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app_with_db(monkeypatch, DEAD_DB)
    resp = app.test_client().get(f"{BASE}/nope")
    assert resp.status_code == 404
    assert resp.mimetype == "application/problem+json"
    assert resp.get_json()["status"] == 404
