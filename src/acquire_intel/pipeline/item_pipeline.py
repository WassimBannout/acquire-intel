"""The Scrapy item pipeline: validate → normalize → dedup (T1.4, ADR-0008/0010).

A thin adapter over ``normalize.py``. For each item the extractor emits it:

1. re-asserts the boundary — only a ``RawProduct`` may pass (anything else is dropped);
2. normalizes it to a canonical ``Product`` + ``PriceObservation`` (rejecting unmappable
   items, e.g. bad price / no currency / empty title);
3. dedups within the run by canonical product id (keep-first);

tracking ``items_ok`` / ``items_rejected`` / ``items_duplicate`` so the crawl-run ledger
(T1.5) can record them. A dropped item is never persisted (ADR-0008).

Run context — ``source_id``, ``run_id``, and the source's ``default_currency`` — is read from
the spider at ``open_spider``; the persistence pipeline (T1.5) consumes the ``NormalizedItem``
this stage returns.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from scrapy.exceptions import DropItem

from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.monitoring.logging import get_logger
from acquire_intel.pipeline.normalize import NormalizationError, NormalizedItem, normalize

if TYPE_CHECKING:
    from scrapy import Spider

_log = get_logger("acquire_intel.pipeline.normalize")

STAT_ITEMS_REJECTED = "acquire/items_rejected"
STAT_ITEMS_DUPLICATE = "acquire/items_duplicate"


def _inc_stat(spider: Spider, key: str) -> None:
    """Bump a Scrapy stat if the crawler exposes one (a no-op in bare unit tests)."""
    stats = getattr(getattr(spider, "crawler", None), "stats", None)
    if stats is not None:
        stats.inc_value(key)


class NormalizePipeline:
    """Validate, normalize, and dedup extractor output before persistence."""

    def open_spider(self, spider: Spider) -> None:
        # Source config is carried on the spider until the sources table drives it (T1.5/T1.7).
        self.source_id: str = getattr(spider, "id", spider.name)
        self.run_id: str = getattr(spider, "run_id", None) or uuid.uuid4().hex
        self.default_currency: str | None = getattr(spider, "default_currency", None)
        self._seen: set[str] = set()
        self.items_ok = 0
        self.items_rejected = 0
        self.items_duplicate = 0

    def process_item(self, item: object, spider: Spider) -> NormalizedItem:
        if not isinstance(item, RawProduct):
            self.items_rejected += 1
            _inc_stat(spider, STAT_ITEMS_REJECTED)
            raise DropItem(f"not a RawProduct: {type(item).__name__}")

        try:
            normalized = normalize(
                item,
                source_id=self.source_id,
                run_id=self.run_id,
                captured_at=datetime.now(UTC),  # stamped at capture time
                default_currency=self.default_currency,
            )
        except NormalizationError as exc:
            self.items_rejected += 1
            _inc_stat(spider, STAT_ITEMS_REJECTED)
            _log.warning("pipeline.item_rejected", external_id=item.external_id, reason=str(exc))
            raise DropItem(str(exc)) from exc

        product_id = normalized.product.id
        if product_id in self._seen:
            self.items_duplicate += 1
            _inc_stat(spider, STAT_ITEMS_DUPLICATE)
            _log.info("pipeline.item_deduped", product_id=product_id)
            raise DropItem(f"duplicate within run: {product_id}")

        self._seen.add(product_id)
        self.items_ok += 1
        return normalized

    def close_spider(self, spider: Spider) -> None:
        _log.info(
            "pipeline.finished",
            items_ok=self.items_ok,
            items_rejected=self.items_rejected,
            items_duplicate=self.items_duplicate,
        )
