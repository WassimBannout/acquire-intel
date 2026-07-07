"""The Scrapy persistence pipeline: canonical item → Postgres (T1.7 + T3.5, ADR-0006/0012).

Runs after :class:`~acquire_intel.pipeline.item_pipeline.NormalizePipeline` (@300) and
:class:`~acquire_intel.pipeline.quality.QualityGatePipeline` (@350) and is the last stage (@400).

Since T3.5 (ADR-0012 §3) this stage is **run-atomic** w.r.t. the volume gate: it does not write
per item, it **buffers** the surviving ``NormalizedItem``s and, at ``close_spider``, evaluates the
volume gate (this run's count vs. the source's recent committed baseline). If the count is within
tolerance it **flushes** the whole buffer — upsert the ``products`` projection, append the immutable
``price_observation``, one short transaction per item; if it breaches, it **commits nothing**,
records the anomaly, and the runner marks the run ``quarantined``. Append-only storage has no
delete (ADR-0006), so "quarantined, not committed" can only be honoured by deferring the write.

Only **persistable** sources (a real ``SourceExtractor`` — carrying a ``kind`` and a bound
``run_id``) touch the DB; the no-op ``demo`` spider passes items straight through so a crawl with
no DB (T0.4) still works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from acquire_intel.monitoring.logging import get_logger
from acquire_intel.pipeline.normalize import NormalizedItem
from acquire_intel.pipeline.quality import GateThresholds, QualityIssue, check_volume
from acquire_intel.storage import (
    CrawlRunRepository,
    PriceObservationRepository,
    ProductRepository,
    session_scope,
)

if TYPE_CHECKING:
    from scrapy import Spider

_log = get_logger("acquire_intel.pipeline.persistence")

STAT_ITEMS_PERSISTED = "acquire/items_persisted"
# Run-level flag the runner reads to set status="quarantined" (a volume-gated run commits nothing).
STAT_QUALITY_QUARANTINED = "acquire/quality_quarantined"


class PersistencePipeline:
    """Buffer canonical items, then flush to Postgres at close only if the volume gate passes."""

    def open_spider(self, spider: Spider) -> None:
        # Persist only for real extractors that opened a run; the no-op demo stays DB-free.
        self.enabled: bool = getattr(spider, "kind", None) is not None and bool(
            getattr(spider, "run_id", None)
        )
        self.source_id: str = getattr(spider, "id", spider.name)
        self.run_id: str = getattr(spider, "run_id", "")
        settings = getattr(getattr(spider, "crawler", None), "settings", None)
        self.thresholds = (
            GateThresholds.from_settings(settings) if settings is not None else GateThresholds()
        )
        self._buffer: list[NormalizedItem] = []
        self.persisted = 0
        self.baseline: int | None = None
        if self.enabled:
            with session_scope() as session:
                self.baseline = CrawlRunRepository(session).baseline_count(
                    self.source_id, exclude_run_id=self.run_id
                )

    def process_item(self, item: object, spider: Spider) -> object:
        # Buffer survivors; the volume gate at close decides whether any of them commit.
        if self.enabled and isinstance(item, NormalizedItem):
            self._buffer.append(item)
        return item

    def close_spider(self, spider: Spider) -> None:
        if not self.enabled:
            return
        count = len(self._buffer)
        issue = check_volume(count, self.baseline, self.thresholds)
        if issue is QualityIssue.VOLUME_ANOMALY:
            _inc_stat(spider, STAT_QUALITY_QUARANTINED)
            _inc_stat(spider, f"acquire/quality/{issue.value}")
            _log.warning(
                "persistence.volume_quarantined",
                source_id=self.source_id,
                count=count,
                baseline=self.baseline,
                committed=0,
            )
            return  # not committed: the run's observations are quarantined wholesale

        for item in self._buffer:
            with session_scope() as session:
                ProductRepository(session).upsert(item.product)
                PriceObservationRepository(session).append(item.observation)
            self.persisted += 1
            _inc_stat(spider, STAT_ITEMS_PERSISTED)
        _log.info("persistence.finished", persisted=self.persisted, baseline=self.baseline)


def _inc_stat(spider: Spider, key: str) -> None:
    stats = getattr(getattr(spider, "crawler", None), "stats", None)
    if stats is not None:
        stats.inc_value(key)
