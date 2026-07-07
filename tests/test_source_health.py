"""Per-source health + metrics tests (T4.4, docs/07 §2 & §4, specs/openapi.yaml getSourceHealth).

Two layers:

* **Pure** unit tests for :func:`acquire_intel.analytics.health.classify_source` /
  :func:`overall_status` — each of healthy/degraded/stale/failing + the ban-rate math, no DB.
* **Integration** tests driving the Flask client against live Postgres over **seeded**
  ``crawl_runs`` that realize each classification, asserting ``GET /health/sources`` (per-source +
  overall rollup) and the ``GET /metrics`` catalog. Skips when no DB is configured/reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from acquire_intel import contracts
from acquire_intel.analytics.health import RunPoint, classify_source, overall_status
from acquire_intel.api import create_app
from acquire_intel.config import ConfigError, get_settings
from acquire_intel.storage import (
    BanEventRepository,
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

BASE = "/api/v1"
_TABLES = "ban_events, price_observations, crawl_runs, products, sources"
_STALE_AFTER = 21_600  # 6h, matching the seeded sources

# classification thresholds (settings defaults)
_DEG = 0.2
_FAIL = 0.5


# --------------------------------------------------------------------------- pure


def _run(status: str, *, at: datetime, bans: int = 0, requests: int = 0) -> RunPoint:
    return RunPoint(
        status=status,
        started_at=at,
        finished_at=at,
        items_ok=1,
        items_rejected=0,
        ban_events=bans,
        requests=requests,
    )


def _classify(runs: list[RunPoint], *, now: datetime) -> str:
    return classify_source(
        "s",
        runs,
        stale_after_seconds=_STALE_AFTER,
        now=now,
        degraded_ban_rate=_DEG,
        fail_ban_rate=_FAIL,
    ).status


def test_classify_healthy() -> None:
    now = datetime.now(UTC)
    assert _classify([_run("success", at=now, requests=20)], now=now) == "healthy"


def test_classify_stale_when_last_success_old() -> None:
    now = datetime.now(UTC)
    old = now - timedelta(seconds=_STALE_AFTER + 3600)
    assert _classify([_run("success", at=old, requests=20)], now=now) == "stale"


def test_classify_no_runs_is_stale() -> None:
    assert _classify([], now=datetime.now(UTC)) == "stale"


def test_classify_degraded_on_partial() -> None:
    now = datetime.now(UTC)
    assert _classify([_run("partial", at=now, requests=20)], now=now) == "degraded"


def test_classify_degraded_on_elevated_ban_rate() -> None:
    now = datetime.now(UTC)
    # ban_rate 5/20 = 0.25 (>= 0.2, < 0.5): degraded despite a fresh success.
    assert _classify([_run("success", at=now, bans=5, requests=20)], now=now) == "degraded"


def test_classify_failing_on_failed_latest() -> None:
    now = datetime.now(UTC)
    assert _classify([_run("failed", at=now, requests=20)], now=now) == "failing"


def test_classify_failing_on_high_ban_rate() -> None:
    now = datetime.now(UTC)
    # ban_rate 12/20 = 0.6 (>= 0.5): failing even though the run "succeeded".
    summary = classify_source(
        "s",
        [_run("success", at=now, bans=12, requests=20)],
        stale_after_seconds=_STALE_AFTER,
        now=now,
        degraded_ban_rate=_DEG,
        fail_ban_rate=_FAIL,
    )
    assert summary.status == "failing"
    assert summary.ban_rate == pytest.approx(0.6)


def test_ban_rate_none_without_requests() -> None:
    now = datetime.now(UTC)
    summary = classify_source(
        "s",
        [_run("success", at=now, bans=3, requests=0)],
        stale_after_seconds=_STALE_AFTER,
        now=now,
        degraded_ban_rate=_DEG,
        fail_ban_rate=_FAIL,
    )
    assert summary.ban_rate is None


def test_overall_status_is_worst() -> None:
    assert overall_status(["healthy", "degraded", "stale"]) == "stale"
    assert overall_status(["healthy", "stale", "failing"]) == "failing"
    assert overall_status([]) == "healthy"
    assert overall_status(["healthy", "degraded"]) == "degraded"


# ----------------------------------------------------------------------- view (DB)

pytestmark = pytest.mark.integration


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
            stale_after_seconds=_STALE_AFTER,
            crawl_policy={},
        )
    )
    session.commit()


def _seed_run(
    session: Session,
    source_id: str,
    *,
    status: str,
    finished_at: datetime,
    requests: int = 0,
    bans: int = 0,
    kind: str = "blocked",
    action: str = "rotate_identity",
) -> None:
    """Seed one closed run (+ ``bans`` matching ban_events rows) realizing a health state."""
    runs = CrawlRunRepository(session)
    run_id = f"{source_id}-{status}-{finished_at.isoformat()}"
    runs.open(run_id=run_id, source_id=source_id, started_at=finished_at)
    if bans:
        BanEventRepository(session).record(
            run_id,
            [
                contracts.BanEvent(
                    kind=kind, action_taken=action, http_status=403, occurred_at=finished_at
                )
                for _ in range(bans)
            ],
        )
    runs.close(
        run_id,
        status=status,
        items_ok=1 if status in {"success", "partial"} else 0,
        items_rejected=0,
        ban_events=bans,
        finished_at=finished_at,
        timings={"requests": requests},
    )
    session.commit()


def test_health_sources_classifies_each_state(app: Flask, session: Session) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(seconds=_STALE_AFTER + 3600)
    for sid in ("healthy_src", "stale_src", "degraded_src", "failing_src", "quiet_src"):
        _seed_source(session, sid)
    _seed_run(session, "healthy_src", status="success", finished_at=now, requests=20)
    _seed_run(session, "stale_src", status="success", finished_at=old, requests=20)
    _seed_run(session, "degraded_src", status="partial", finished_at=now, requests=20)
    _seed_run(session, "failing_src", status="success", finished_at=now, requests=20, bans=12)
    # quiet_src: registered but never run -> stale.

    body = app.test_client().get(f"{BASE}/health/sources").get_json()
    by_source = {s["source"]: s for s in body["sources"]}
    assert by_source["healthy_src"]["status"] == "healthy"
    assert by_source["stale_src"]["status"] == "stale"
    assert by_source["degraded_src"]["status"] == "degraded"
    assert by_source["failing_src"]["status"] == "failing"
    assert by_source["quiet_src"]["status"] == "stale"

    # ban-rate exposed + spec fields present.
    assert by_source["failing_src"]["banRate"] == pytest.approx(0.6)
    assert by_source["healthy_src"]["banRate"] == 0.0
    assert by_source["quiet_src"]["banRate"] is None
    assert by_source["healthy_src"]["staleAfterSeconds"] == _STALE_AFTER
    assert by_source["healthy_src"]["lastRunStatus"] == "success"

    # overall rolls up to the worst.
    assert body["overall"] == "failing"


def test_metrics_catalog_shape(app: Flask, session: Session) -> None:
    now = datetime.now(UTC)
    _seed_source(session, "demo_rest")
    _seed_run(
        session, "demo_rest", status="success", finished_at=now, requests=20, bans=2, kind="captcha"
    )
    _seed_run(session, "demo_rest", status="failed", finished_at=now, requests=10)

    body = app.test_client().get(f"{BASE}/metrics").get_json()
    assert "generatedAt" in body
    src = body["sources"]["demo_rest"]
    # crawl_runs_total counter (per status), ban_events_total (per kind), ban-rate.
    assert src["crawlRunsTotal"]["success"] == 1
    assert src["crawlRunsTotal"]["failed"] == 1
    assert src["banEventsTotal"]["captcha"] == 2
    assert src["banRate"] == round(2 / 30, 4)  # ban events / requests, rounded for presentation
    # rotations catalog (from ban_events.action_taken).
    assert body["rotations"]["identity"] == 2
    assert body["rotations"]["proxy"] == 0
