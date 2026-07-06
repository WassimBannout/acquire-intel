"""The Scrapy persistence pipeline: canonical item → Postgres (T1.7, ADR-0006).

Runs after :class:`~acquire_intel.pipeline.item_pipeline.NormalizePipeline` and is the last
stage: it takes the ``NormalizedItem`` that stage produced and writes it through the
repositories — upsert the ``products`` projection, append the immutable ``price_observation`` —
in one short transaction per item. The observation's ``run_id`` references the ``crawl_runs``
row the runner opened before the crawl (its FK), so the run must exist first.

Only **persistable** sources (a real ``SourceExtractor`` — one carrying a ``kind`` and a bound
``run_id``) touch the DB; the no-op ``demo`` spider passes items straight through so a crawl
with no DB (T0.4) still works. Each persisted item bumps a Scrapy stat the runner reads to
close the crawl-run ledger with a truthful ``items_ok`` count.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from acquire_intel.monitoring.logging import get_logger
from acquire_intel.pipeline.normalize import NormalizedItem
from acquire_intel.storage import (
    PriceObservationRepository,
    ProductRepository,
    session_scope,
)

if TYPE_CHECKING:
    from scrapy import Spider

_log = get_logger("acquire_intel.pipeline.persistence")

STAT_ITEMS_PERSISTED = "acquire/items_persisted"


class PersistencePipeline:
    """Persist canonical items to Postgres (upsert product + append observation)."""

    def open_spider(self, spider: Spider) -> None:
        # Persist only for real extractors that opened a run; the no-op demo stays DB-free.
        self.enabled: bool = getattr(spider, "kind", None) is not None and bool(
            getattr(spider, "run_id", None)
        )
        self.persisted = 0

    def process_item(self, item: object, spider: Spider) -> object:
        if not self.enabled or not isinstance(item, NormalizedItem):
            return item

        with session_scope() as session:
            ProductRepository(session).upsert(item.product)
            PriceObservationRepository(session).append(item.observation)

        self.persisted += 1
        stats = getattr(getattr(spider, "crawler", None), "stats", None)
        if stats is not None:
            stats.inc_value(STAT_ITEMS_PERSISTED)
        return item

    def close_spider(self, spider: Spider) -> None:
        if self.enabled:
            _log.info("persistence.finished", persisted=self.persisted)
