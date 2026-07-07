"""Crawl runner: CLI/scheduler entrypoint into the Scrapy engine.

Generates a ``run_id``, binds it to the log context, resolves the source's spider via the
registry, and runs a one-shot crawl — logging ``crawl.started`` / ``crawl.finished`` with stats.

For a **persistable** source (a real ``SourceExtractor`` carrying a ``kind``) the runner also
drives the crawl-run ledger (T1.5/T1.7): it loads the source's config from the ``sources``
registry, opens a ``crawl_runs`` row (``running``) **before** the crawl so persisted
observations' ``run_id`` FK resolves, passes ``run_id``/``base_url``/``default_currency`` into
the spider, and closes the run with a terminal status + item counts afterward (even on error).
The no-op ``demo`` spider has no ``kind`` and touches no DB (T0.4 semantics preserved).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from scrapy.crawler import CrawlerProcess

from acquire_intel.acquisition.registry import get_spider, known_sources
from acquire_intel.acquisition.scrapy_settings import build_scrapy_settings
from acquire_intel.acquisition.telemetry import STAT_ENTRIES_MAPPED, STAT_ENTRIES_SEEN
from acquire_intel.analytics.drift import assess_drift
from acquire_intel.config import get_settings
from acquire_intel.monitoring.logging import bind_run, configure_logging, get_logger
from acquire_intel.pipeline.item_pipeline import STAT_ITEMS_REJECTED
from acquire_intel.pipeline.persistence import STAT_ITEMS_PERSISTED, STAT_QUALITY_QUARANTINED
from acquire_intel.storage import (
    BanEventRepository,
    CrawlRunRepository,
    SourceRepository,
    session_scope,
)

if TYPE_CHECKING:
    from scrapy.crawler import Crawler

    from acquire_intel.contracts import BanEvent, RunStatus

_DEFAULT_CURRENCY = "USD"


def run_crawl(source_id: str) -> int:
    """Run a one-shot crawl for ``source_id``. Returns a process exit code.

    ``0`` on a completed crawl; ``2`` if the source is unknown or (for a persistable source)
    not registered in the ``sources`` table.
    """
    configure_logging()
    run_id = uuid.uuid4().hex
    log = get_logger("acquire_intel.crawl")

    with bind_run(run_id=run_id, source=source_id):
        spider_cls = get_spider(source_id)
        if spider_cls is None:
            log.error("crawl.unknown_source", known_sources=known_sources())
            return 2

        persistable = getattr(spider_cls, "kind", None) is not None
        crawl_kwargs: dict[str, Any] = {}
        ban_sink: list[BanEvent] = []  # the ban-detection middleware appends detected events here
        if persistable:
            source = _load_source(source_id)
            if source is None:
                log.error("crawl.unregistered_source", detail="no sources row; register it first")
                return 2
            crawl_kwargs = {
                "run_id": run_id,
                "base_url": source["base_url"],
                "default_currency": source["default_currency"],
                "ban_events": ban_sink,  # shared list: middleware fills it, we persist it below
            }
            _open_run(run_id, source_id)

        log.info("crawl.started", spider=spider_cls.name)
        process = CrawlerProcess(settings=build_scrapy_settings(), install_root_handler=False)
        # Hold the Crawler reference: process.crawlers is emptied once start() returns.
        crawler = process.create_crawler(spider_cls)
        process.crawl(crawler, **crawl_kwargs)
        try:
            process.start()  # blocks until the crawl finishes and the reactor stops
        except Exception:
            if persistable:
                _close_run(
                    run_id, status="failed", items_ok=0, items_rejected=0, ban_events=ban_sink
                )
            log.exception("crawl.crashed")
            raise

        stats = _collect_stats(crawler)
        cfg = get_settings()
        drift = assess_drift(
            int(stats["entries_seen"]),
            int(stats["entries_mapped"]),
            min_entries=cfg.drift_min_entries,
            max_unmapped_ratio=cfg.drift_max_unmapped_ratio,
        )
        log.info("crawl.finished", **stats, ban_events=len(ban_sink), drift=drift)
        if drift:
            # A format change: entries were seen but did not map. Alert, don't crash (FR-16).
            log.warning(
                "crawl.drift_detected",
                entries_seen=stats["entries_seen"],
                entries_mapped=stats["entries_mapped"],
            )
        if persistable:
            items_ok = int(stats["items_ok"])
            items_rejected = int(stats["items_rejected"])
            _close_run(
                run_id,
                status=_run_status(
                    stats["finish_reason"], items_rejected, int(stats["quarantined"]), drift=drift
                ),
                items_ok=items_ok,
                items_rejected=items_rejected,
                ban_events=ban_sink,
                requests=int(stats["requests"]),
            )
        return 0


def _load_source(source_id: str) -> dict[str, Any] | None:
    """Read a source's crawl config from the registry, or ``None`` if unregistered."""
    with session_scope() as session:
        source = SourceRepository(session).get(source_id)
        if source is None:
            return None
        policy = source.crawl_policy or {}
        return {
            "base_url": source.base_url,
            "default_currency": policy.get("default_currency", _DEFAULT_CURRENCY),
        }


def _open_run(run_id: str, source_id: str) -> None:
    with session_scope() as session:
        CrawlRunRepository(session).open(
            run_id=run_id, source_id=source_id, started_at=datetime.now(UTC)
        )


def _close_run(
    run_id: str,
    *,
    status: RunStatus,
    items_ok: int,
    items_rejected: int,
    ban_events: list[BanEvent],
    requests: int = 0,
) -> None:
    with session_scope() as session:
        # Append the run's ban audit trail (docs/03 §2.4) and record the count on the ledger row.
        recorded = BanEventRepository(session).record(run_id, ban_events)
        CrawlRunRepository(session).close(
            run_id,
            status=status,
            items_ok=items_ok,
            items_rejected=items_rejected,
            ban_events=recorded,
            # ``requests`` powers the ban-rate metric (ban events / requests, docs/07 §4).
            timings={"requests": requests},
            finished_at=datetime.now(UTC),
        )


def _run_status(
    finish_reason: object, items_rejected: int, quarantined: int, *, drift: bool = False
) -> RunStatus:
    """Map the Scrapy finish reason + reject/quarantine/drift signals to a ledger status."""
    if finish_reason != "finished":
        return "failed"
    if drift:  # a format change — entries seen but unmappable; alert, don't crash (ADR-0014)
        return "flagged"
    if quarantined > 0:  # volume gate tripped → the whole run committed nothing (ADR-0012)
        return "quarantined"
    return "partial" if items_rejected > 0 else "success"


def _collect_stats(crawler: Crawler) -> dict[str, Any]:
    """Extract a small, stable summary from the crawl's Scrapy stats."""
    stats = crawler.stats.get_stats() if crawler.stats is not None else {}
    return {
        "items": stats.get("item_scraped_count", 0),
        "items_ok": stats.get(STAT_ITEMS_PERSISTED, 0),
        "items_rejected": stats.get(STAT_ITEMS_REJECTED, 0),
        "quarantined": stats.get(STAT_QUALITY_QUARANTINED, 0),
        "entries_seen": stats.get(STAT_ENTRIES_SEEN, 0),
        "entries_mapped": stats.get(STAT_ENTRIES_MAPPED, 0),
        "requests": stats.get("downloader/request_count", 0),
        "finish_reason": stats.get("finish_reason"),
    }
