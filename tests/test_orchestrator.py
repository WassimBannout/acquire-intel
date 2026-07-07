"""Crawl-orchestration tests (T4.5, ADR-0016).

* **Trigger unit** (stubbed launch): resolving targets (all vs. named vs. unknown) and that
  ``trigger_crawl`` opens a ``running`` ledger row per target and returns it.
* **Real end-to-end**: ``trigger_crawl`` against the adversarial harness with a *blocking* launcher
  that runs the actual CLI ``crawl --run-id`` subprocess — proving the subprocess adopts the
  pre-opened run, crawls, closes it ``success``, and persists observations (CLI/HTTP/scheduler share
  one path). Skips when no Postgres is configured.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from typing import TYPE_CHECKING
from wsgiref.simple_server import WSGIServer, make_server

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from acquire_intel.acquisition.orchestrator import UnknownSourceError, trigger_crawl
from acquire_intel.config import ConfigError
from acquire_intel.storage import (
    CrawlRunRepository,
    PriceObservationRepository,
    Source,
    SourceRepository,
    get_engine,
    new_session,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

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


def _seed_source(session: Session, source_id: str, *, base_url: str | None = None) -> None:
    SourceRepository(session).add(
        Source(
            id=source_id,
            kind="rest",
            base_url=base_url or f"https://{source_id}.example.com",
            stale_after_seconds=21_600,
            crawl_policy={"default_currency": "USD"},
        )
    )
    session.commit()


def _recorder() -> tuple[list[tuple[str, str]], object]:
    calls: list[tuple[str, str]] = []
    return calls, lambda source_id, run_id: calls.append((source_id, run_id))


def test_trigger_all_opens_a_running_run_per_source(session: Session) -> None:
    _seed_source(session, "demo_rest")
    _seed_source(session, "demo_graphql")
    calls, spawn = _recorder()

    runs = trigger_crawl(None, spawn=spawn)  # type: ignore[arg-type]

    assert {r.source for r in runs} == {"demo_rest", "demo_graphql"}
    assert all(r.status == "running" for r in runs)
    assert {s for s, _ in calls} == {"demo_rest", "demo_graphql"}
    reader = new_session()
    try:
        for r in runs:
            assert CrawlRunRepository(reader).get(r.id) is not None
    finally:
        reader.close()


def test_unknown_or_unregistered_source_raises(session: Session) -> None:
    _seed_source(session, "demo_rest")
    calls, spawn = _recorder()

    # Not in the sources table at all.
    with pytest.raises(UnknownSourceError):
        trigger_crawl(["nope"], spawn=spawn)  # type: ignore[arg-type]
    # 'demo' has a spider but is not a registered (persistable) source row.
    with pytest.raises(UnknownSourceError):
        trigger_crawl(["demo"], spawn=spawn)  # type: ignore[arg-type]
    assert calls == []  # nothing launched on an invalid target


# --- real end-to-end via the harness -----------------------------------------------------


@pytest.fixture
def harness_url() -> Iterator[str]:
    """A live adversarial-harness server; yields its base URL."""
    from harness.server import create_harness_app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server: WSGIServer = make_server("127.0.0.1", port, create_harness_app())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()


def _blocking_cli_spawn(source_id: str, run_id: str) -> None:
    """Run the real CLI crawl synchronously (so the test can assert after it finishes)."""
    env = {
        **os.environ,
        "ROBOTSTXT_OBEY": "false",
        "AUTOTHROTTLE_ENABLED": "false",
        "DEFAULT_DOWNLOAD_DELAY": "0",
    }
    subprocess.run(
        [sys.executable, "-m", "acquire_intel.cli", "crawl", source_id, "--run-id", run_id],
        check=True,
        capture_output=True,
        timeout=120,
        env=env,
    )


def test_trigger_runs_the_real_cli_end_to_end(session: Session, harness_url: str) -> None:
    _seed_source(session, "demo_rest", base_url=f"{harness_url}/happy")

    runs = trigger_crawl(["demo_rest"], spawn=_blocking_cli_spawn)
    assert len(runs) == 1
    run_id = runs[0].id

    reader = new_session()
    try:
        row = CrawlRunRepository(reader).get(run_id)
        assert row is not None
        # The subprocess adopted the pre-opened run and closed it — no second row opened.
        assert row.status == "success"
        assert row.items_ok == 3
        assert PriceObservationRepository(reader).count_for("demo_rest:9001") == 1
    finally:
        reader.close()
