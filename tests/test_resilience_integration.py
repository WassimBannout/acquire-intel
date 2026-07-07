"""T3.6 — resilience integration, the M3 gate (ADR-0005/0009/0012, docs/04, docs/06 §4).

The milestone-closing proof: a **real** ``acquire-intel crawl`` subprocess drives the whole stack
(resilience downloader middlewares → ban gate → quality gates → persistence → crawl-run + ban
ledger) against the adversarial harness, once per scenario, into Postgres. It asserts, end to end:

* **recovery** — ``happy`` / ``rate_limited`` (backoff) / ``block_after_n`` (identity rotation) all
  yield the full catalogue;
* **ban recording** — ``captcha`` / ``soft_ban`` land ``ban_events`` rows with the right kind and
  action;
* **zero garbage** — a blocked/invalid/empty response never becomes a ``price_observation``: every
  ban scenario persists **0** observations.

Reactor-per-process means one crawl per subprocess (as the T1.7 E2E does); the harness runs in a
thread in the test process and the subprocess reaches it over a real socket. Skips when Postgres is
unreachable. Per-scenario recovery of ``cookie_wall``/``drift`` is additionally proven at the unit
level (``test_rotation_middleware``, ``test_ban_classifier``, the extractor drift fixtures).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import urllib.request
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from acquire_intel.config import ConfigError
from acquire_intel.storage import (
    BanEventRepository,
    CrawlRun,
    PriceObservation,
    Source,
    SourceRepository,
    get_engine,
    new_session,
    session_scope,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

pytestmark = pytest.mark.integration

_SOURCE_ID = "demo_rest"
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


@pytest.fixture(scope="module")
def harness() -> Iterator[str]:
    """Run the adversarial harness in a thread; ``block_after=1`` so a block forces a rotation."""
    from werkzeug.serving import make_server

    from harness import HarnessConfig, create_harness_app

    app = create_harness_app(HarnessConfig(block_after=1))
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _truncate(engine: Engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))


def _reset_harness(base: str) -> None:
    urllib.request.urlopen(
        urllib.request.Request(f"{base}/__admin__/reset", method="POST"), timeout=5
    ).close()


def _register(scenario_url: str) -> None:
    with session_scope() as session:
        SourceRepository(session).add(
            Source(
                id=_SOURCE_ID,
                kind="rest",
                base_url=scenario_url,
                stale_after_seconds=21_600,
                crawl_policy={"default_currency": "USD"},
            )
        )


def _crawl() -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "FLASK_SECRET_KEY": "test",
        "ADMIN_TOKEN": "test",
        "ROBOTSTXT_OBEY": "false",
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


# scenario -> (expected observations persisted, expected ban kind or None for a clean recovery)
_CASES = [
    ("happy", 3, None),
    ("rate_limited", 3, None),  # backoff honours Retry-After, then succeeds
    ("block_after_n", 3, None),  # 403 → rotate identity → fresh budget → full catalogue
    ("captcha", 0, "captcha"),  # challenge page, never data
    ("soft_ban", 0, "empty"),  # 200 empty body, a silent block
]


@pytest.mark.parametrize(("scenario", "expected_obs", "expected_ban"), _CASES)
def test_resilience_scenario_end_to_end(
    engine: Engine, harness: str, scenario: str, expected_obs: int, expected_ban: str | None
) -> None:
    _truncate(engine)
    _reset_harness(harness)
    _register(f"{harness}/{scenario}")

    result = _crawl()
    assert result.returncode == 0, result.stderr

    reader = new_session()
    try:
        obs_count = reader.scalar(select(func.count()).select_from(PriceObservation)) or 0
        runs = list(reader.scalars(select(CrawlRun)))
        assert len(runs) == 1, "exactly one crawl run per scenario"
        run = runs[0]
        bans = BanEventRepository(reader).list_for(run.id)

        # Recovery / zero-garbage: the observation count matches the scenario's outcome exactly.
        assert obs_count == expected_obs, f"{scenario}: observations"

        if expected_ban is None:
            # A clean recovery (or happy path): nothing was blocked past the resilience layer.
            assert bans == [], f"{scenario}: expected no bans, got {[b.kind for b in bans]}"
        else:
            # A block/CAPTCHA/soft-ban: recorded with the right kind/action, and NOT stored as data.
            kinds = {b.kind for b in bans}
            assert expected_ban in kinds, f"{scenario}: expected a {expected_ban} ban, got {kinds}"
            assert all(b.action_taken == "rotate_identity" for b in bans if b.kind == expected_ban)
            assert obs_count == 0, f"{scenario}: a ban must never be persisted as data"
        # The ledger's ban count agrees with the audit-trail rows.
        assert run.ban_events == len(bans)
    finally:
        reader.close()
        _truncate(engine)
