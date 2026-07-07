"""Crawl orchestration — the one trigger shared by the scheduler and ``POST /admin/crawl`` (T4.5).

Scrapy's Twisted reactor can be started only once per process, so a long-lived process (the API +
its in-process scheduler) cannot run crawls in-process repeatedly. The reconciliation (ADR-0016):
the crawl **executor** stays the CLI (``run_crawl``, one reactor per process); the **trigger** here
opens the ``crawl_runs`` ledger row(s) synchronously (status ``running``) and launches each crawl as
a **detached subprocess** that invokes the CLI with the pre-created ``--run-id``, then returns the
running rows immediately. So a ``POST /admin/crawl`` gets a non-blocking ``202`` with a real run to
report, every crawl gets a fresh reactor + process isolation, and the scheduler/HTTP paths run the
exact same CLI an operator would (CLI parity).
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from acquire_intel.acquisition.registry import get_spider
from acquire_intel.monitoring.logging import get_logger
from acquire_intel.storage import CrawlRunRepository, SourceRepository, session_scope

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.orm import Session

_log = get_logger("acquire_intel.orchestrator")


class UnknownSourceError(Exception):
    """A crawl was requested for a source that is not registered/persistable."""

    def __init__(self, source_id: str) -> None:
        super().__init__(source_id)
        self.source_id = source_id


@dataclass(frozen=True)
class TriggeredRun:
    """A just-opened crawl run (status ``running``) reported back to the trigger's caller."""

    id: str
    source: str
    status: str
    started_at: datetime


def _spawn_crawl(source_id: str, run_id: str) -> None:
    """Launch a detached crawl subprocess adopting ``run_id`` (the default, real launcher)."""
    # Fixed argv, no shell; ids are ours (a uuid + a registry key), never user-interpolated.
    subprocess.Popen(
        [sys.executable, "-m", "acquire_intel.cli", "crawl", source_id, "--run-id", run_id],
        start_new_session=True,  # detach from the API/scheduler process group
    )


def _resolve_targets(session: Session, source_ids: Sequence[str] | None) -> list[str]:
    """Resolve the crawl target ids: an explicit list (validated) or every registered source."""
    registered = SourceRepository(session).list_ids()
    if source_ids is None:
        return registered
    known = set(registered)
    for sid in source_ids:
        if sid not in known or get_spider(sid) is None:
            raise UnknownSourceError(sid)
    return list(source_ids)


def trigger_crawl(
    source_ids: Sequence[str] | None = None,
    *,
    spawn: Callable[[str, str], None] | None = None,
) -> list[TriggeredRun]:
    """Open a ``running`` ledger row per target source and launch its crawl; return the runs.

    ``source_ids=None`` targets every registered source. Rows are committed **before** the
    subprocess starts so the crawl (a separate connection) sees its own ``crawl_runs`` row. Raises
    :class:`UnknownSourceError` if any named source is not registered/persistable. ``spawn`` (the
    launcher) is injectable — and resolved at call time — so tests run no real Scrapy subprocess.
    """
    launch = spawn or _spawn_crawl
    now = datetime.now(UTC)
    triggered: list[TriggeredRun] = []
    with session_scope() as session:
        targets = _resolve_targets(session, source_ids)
        runs = CrawlRunRepository(session)
        for source_id in targets:
            run_id = uuid.uuid4().hex
            runs.open(run_id=run_id, source_id=source_id, started_at=now)
            triggered.append(
                TriggeredRun(id=run_id, source=source_id, status="running", started_at=now)
            )
    # Committed above; now launch each crawl (the subprocess adopts the pre-opened run_id).
    for run in triggered:
        launch(run.source, run.id)
        _log.info("crawl.triggered", source=run.source, run_id=run.id)
    return triggered
