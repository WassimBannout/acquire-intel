"""In-process per-source crawl scheduler (T4.5, ADR-0007/0016).

An APScheduler ``BackgroundScheduler`` living in the API process. On start it adds one interval job
per registered source, each calling the shared :func:`trigger_crawl` (the same path the CLI and
``POST /admin/crawl`` use) for that source — so a scheduled tick launches a crawl exactly as a
manual trigger does. A source's interval comes from ``crawl_policy.schedule_seconds``, else the
global default. Off by default (``SCHEDULER_ENABLED``); the operator/demo opts in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.exc import SQLAlchemyError

from acquire_intel.acquisition.orchestrator import trigger_crawl
from acquire_intel.config import get_settings
from acquire_intel.monitoring.logging import get_logger
from acquire_intel.storage import SourceRepository, session_scope

if TYPE_CHECKING:
    from acquire_intel.config import Settings

_log = get_logger("acquire_intel.scheduler")


def _scheduled_crawl(source_id: str) -> None:
    """Scheduler job body: trigger a crawl, never letting an error kill the scheduler."""
    try:
        trigger_crawl([source_id])
    except Exception:  # a scheduled job must never crash the scheduler thread
        _log.exception("scheduler.crawl_failed", source=source_id)


def configure_scheduler(scheduler: BackgroundScheduler, cfg: Settings) -> list[str]:
    """Add one interval job per registered source; returns the scheduled source ids."""
    scheduled: list[str] = []
    with session_scope() as session:
        sources = SourceRepository(session)
        for source_id in sources.list_ids():
            row = sources.get(source_id)
            policy = (row.crawl_policy if row is not None else {}) or {}
            interval = int(policy.get("schedule_seconds", cfg.scheduler_interval_seconds))
            scheduler.add_job(
                _scheduled_crawl,
                "interval",
                seconds=interval,
                args=[source_id],
                id=f"crawl:{source_id}",
                replace_existing=True,
            )
            scheduled.append(source_id)
    return scheduled


def start_scheduler() -> BackgroundScheduler | None:
    """Build, configure, and start the scheduler when enabled; ``None`` otherwise.

    A DB hiccup at boot must not take the API down, so a failed configure is logged and skipped.
    """
    cfg = get_settings()
    if not cfg.scheduler_enabled:
        return None
    scheduler = BackgroundScheduler(daemon=True)
    try:
        scheduled = configure_scheduler(scheduler, cfg)
    except SQLAlchemyError:
        _log.warning("scheduler.configure_failed")
        return None
    scheduler.start()
    _log.info("scheduler.started", sources=scheduled)
    return scheduler
