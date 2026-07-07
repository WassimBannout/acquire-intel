"""In-process scheduler tests (T4.5, ADR-0007/0016).

Covers: disabled-by-default; ``configure_scheduler`` adds one interval job per registered source
(honouring a per-source ``crawl_policy.schedule_seconds``); and a scheduled tick actually triggers a
crawl (records a ``running`` ledger row) with the real subprocess launch stubbed. DB-backed cases
skip when no Postgres is configured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from acquire_intel.acquisition.scheduler import (
    _scheduled_crawl,
    configure_scheduler,
    start_scheduler,
)
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

    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

_TABLES = "ban_events, price_observations, crawl_runs, products, sources"


def test_disabled_by_default_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("ADMIN_TOKEN", "test")
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    get_settings.cache_clear()
    assert start_scheduler() is None


# ----------------------------------------------------------------------- DB-backed

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


def _seed_source(session: Session, source_id: str, *, schedule_seconds: int | None = None) -> None:
    policy = {"schedule_seconds": schedule_seconds} if schedule_seconds is not None else {}
    SourceRepository(session).add(
        Source(
            id=source_id,
            kind="rest",
            base_url=f"https://{source_id}.example.com",
            stale_after_seconds=21_600,
            crawl_policy=policy,
        )
    )
    session.commit()


def test_configure_adds_a_job_per_source(session: Session) -> None:
    _seed_source(session, "demo_rest")  # default interval
    _seed_source(session, "demo_graphql", schedule_seconds=120)  # per-source override
    get_settings.cache_clear()

    scheduler = BackgroundScheduler()
    scheduled = configure_scheduler(scheduler, get_settings())

    assert set(scheduled) == {"demo_rest", "demo_graphql"}
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"crawl:demo_rest", "crawl:demo_graphql"}
    # The per-source policy interval is honoured; the other falls back to the default.
    assert jobs["crawl:demo_graphql"].trigger.interval.total_seconds() == 120
    assert (
        jobs["crawl:demo_rest"].trigger.interval.total_seconds()
        == get_settings().scheduler_interval_seconds
    )


def test_scheduled_tick_triggers_a_crawl(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    launches: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "acquire_intel.acquisition.orchestrator._spawn_crawl",
        lambda source_id, run_id: launches.append((source_id, run_id)),
    )
    _seed_source(session, "demo_rest")

    _scheduled_crawl("demo_rest")  # what the interval job runs on each tick

    assert [s for s, _ in launches] == ["demo_rest"]
    reader = new_session()
    try:
        run_id = launches[0][1]
        row = CrawlRunRepository(reader).get(run_id)
        assert row is not None
        assert row.status == "running"
        assert row.source_id == "demo_rest"
    finally:
        reader.close()
