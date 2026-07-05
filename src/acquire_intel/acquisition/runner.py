"""Crawl runner: CLI/scheduler entrypoint into the Scrapy engine.

Generates a ``run_id``, binds it to the log context, resolves the source's spider
via the registry, and runs a one-shot crawl — logging ``crawl.started`` /
``crawl.finished`` with stats. Persisting the run to ``crawl_runs`` is T1.5.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from scrapy.crawler import CrawlerProcess

from acquire_intel.acquisition.registry import get_spider, known_sources
from acquire_intel.acquisition.scrapy_settings import build_scrapy_settings
from acquire_intel.monitoring.logging import bind_run, configure_logging, get_logger

if TYPE_CHECKING:
    from scrapy.crawler import Crawler


def run_crawl(source_id: str) -> int:
    """Run a one-shot crawl for ``source_id``. Returns a process exit code.

    ``0`` on a completed crawl; ``2`` if the source is not registered.
    """
    configure_logging()
    run_id = uuid.uuid4().hex
    log = get_logger("acquire_intel.crawl")

    with bind_run(run_id=run_id, source=source_id):
        spider_cls = get_spider(source_id)
        if spider_cls is None:
            log.error("crawl.unknown_source", known_sources=known_sources())
            return 2

        log.info("crawl.started", spider=spider_cls.name)
        process = CrawlerProcess(settings=build_scrapy_settings(), install_root_handler=False)
        # Hold the Crawler reference: process.crawlers is emptied once start() returns.
        crawler = process.create_crawler(spider_cls)
        process.crawl(crawler)
        process.start()  # blocks until the crawl finishes and the reactor stops

        log.info("crawl.finished", **_collect_stats(crawler))
        return 0


def _collect_stats(crawler: Crawler) -> dict[str, Any]:
    """Extract a small, stable summary from the crawl's Scrapy stats."""
    stats = crawler.stats.get_stats() if crawler.stats is not None else {}
    return {
        "items": stats.get("item_scraped_count", 0),
        "requests": stats.get("downloader/request_count", 0),
        "finish_reason": stats.get("finish_reason"),
    }
