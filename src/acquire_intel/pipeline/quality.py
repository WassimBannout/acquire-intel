"""Data-quality gates (T3.5, ADR-0012, docs/04 §3, docs/03 §3).

FR-9: beyond shape validation (``RawProduct`` + ``normalize``, ADR-0008/0010) the pipeline
enforces three quality gates and **never silently stores garbage**:

* **range** — a price outside a plausible band (non-positive, or an implausibly huge
  concatenated-digit scrape error) is dropped;
* **continuity** — a product whose price jumps by more than ``max_jump_ratio`` vs. its last
  committed price (either direction) is dropped;
* **volume** — a *run* whose surviving item count falls outside ``±volume_tolerance`` of the
  source's recent baseline is quarantined and commits **nothing** (ADR-0012 §3).

This module is **pure** (no Scrapy, no I/O): the gate functions and ``GateThresholds`` are
unit-testable at every boundary, matching the classifier/backoff/circuit precedent. The
per-item gates are applied by :class:`QualityGatePipeline` (a thin Scrapy adapter, below); the
run-level **volume** gate is applied by the persistence stage at run close, where the surviving
count is finally known (ADR-0012 §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from scrapy.exceptions import DropItem

from acquire_intel.monitoring.logging import get_logger
from acquire_intel.pipeline.normalize import NormalizedItem
from acquire_intel.storage import PriceObservationRepository, session_scope

if TYPE_CHECKING:
    from scrapy import Spider
    from scrapy.settings import BaseSettings

_log = get_logger("acquire_intel.pipeline.quality")


class QualityIssue(StrEnum):
    """The reason a value/observation/run failed a quality gate."""

    OUT_OF_RANGE = "out_of_range"
    DISCONTINUOUS = "discontinuous"
    VOLUME_ANOMALY = "volume_anomaly"


@dataclass(frozen=True)
class GateThresholds:
    """Tunable bounds for the quality gates (from config, ``ACQUIRE_QUALITY_*``)."""

    price_min: Decimal = Decimal("0")
    price_max: Decimal = Decimal("1000000")
    max_jump_ratio: float = 10.0
    volume_tolerance: float = 0.5
    volume_min_baseline: int = 5

    @classmethod
    def from_settings(cls, settings: BaseSettings) -> GateThresholds:
        """Build thresholds from Scrapy settings (prices carried as strings → ``Decimal``)."""
        return cls(
            price_min=Decimal(str(settings.get("ACQUIRE_QUALITY_PRICE_MIN", "0"))),
            price_max=Decimal(str(settings.get("ACQUIRE_QUALITY_PRICE_MAX", "1000000"))),
            max_jump_ratio=settings.getfloat("ACQUIRE_QUALITY_MAX_JUMP_RATIO", 10.0),
            volume_tolerance=settings.getfloat("ACQUIRE_QUALITY_VOLUME_TOLERANCE", 0.5),
            volume_min_baseline=settings.getint("ACQUIRE_QUALITY_VOLUME_MIN_BASELINE", 5),
        )


def check_range(amount: Decimal, thresholds: GateThresholds) -> QualityIssue | None:
    """Return ``OUT_OF_RANGE`` if ``amount`` is outside the plausible price band, else ``None``."""
    if amount < thresholds.price_min or amount > thresholds.price_max:
        return QualityIssue.OUT_OF_RANGE
    return None


def check_continuity(
    new_amount: Decimal, prev_amount: Decimal | None, thresholds: GateThresholds
) -> QualityIssue | None:
    """Return ``DISCONTINUOUS`` if the price jumped more than ``max_jump_ratio`` vs. its last.

    A first-ever observation (``prev_amount is None``) or a non-positive prior (can't form a
    ratio) always passes — continuity is only meaningful against a real prior price.
    """
    if prev_amount is None or prev_amount <= 0 or new_amount <= 0:
        return None
    ratio = max(new_amount / prev_amount, prev_amount / new_amount)
    if ratio > Decimal(str(thresholds.max_jump_ratio)):
        return QualityIssue.DISCONTINUOUS
    return None


def check_volume(
    count: int, baseline: int | None, thresholds: GateThresholds
) -> QualityIssue | None:
    """Return ``VOLUME_ANOMALY`` if a run's surviving count strays from the source baseline.

    Skipped (``None``) when there is no baseline yet or the baseline is smaller than
    ``volume_min_baseline`` — too little history to gate on without false positives.
    """
    if baseline is None or baseline < thresholds.volume_min_baseline:
        return None
    lower = baseline * (1.0 - thresholds.volume_tolerance)
    upper = baseline * (1.0 + thresholds.volume_tolerance)
    if count < lower or count > upper:
        return QualityIssue.VOLUME_ANOMALY
    return None


STAT_ITEMS_REJECTED = "acquire/items_rejected"


def _issue_stat(issue: QualityIssue) -> str:
    return f"acquire/quality/{issue.value}"


class QualityGatePipeline:
    """Per-item quality gates: drop out-of-range / discontinuous items before persistence.

    Ordered **350**, between :class:`~acquire_intel.pipeline.item_pipeline.NormalizePipeline`
    (@300) and :class:`~acquire_intel.pipeline.persistence.PersistencePipeline` (@400). Range
    and continuity are evaluated here and a failing item is dropped + counted — never persisted
    (ADR-0008/0010/0012). The **volume** gate is not here: it is run-level and lives in the
    persistence stage, which knows the surviving count only at close (ADR-0012 §3).

    Continuity needs each product's last committed price; those are preloaded once at
    ``open_spider`` for the source, so a first-ever observation has no prior and always passes.
    """

    def open_spider(self, spider: Spider) -> None:
        self.enabled: bool = getattr(spider, "kind", None) is not None and bool(
            getattr(spider, "run_id", None)
        )
        self.source_id: str = getattr(spider, "id", spider.name)
        settings = getattr(getattr(spider, "crawler", None), "settings", None)
        self.thresholds = (
            GateThresholds.from_settings(settings) if settings is not None else GateThresholds()
        )
        self._prev_prices: dict[str, Decimal] = {}
        if self.enabled:
            with session_scope() as session:
                self._prev_prices = PriceObservationRepository(session).latest_amounts_for_source(
                    self.source_id
                )

    def process_item(self, item: object, spider: Spider) -> object:
        if not self.enabled or not isinstance(item, NormalizedItem):
            return item

        amount = item.observation.amount
        issue = check_range(amount, self.thresholds) or check_continuity(
            amount, self._prev_prices.get(item.product.id), self.thresholds
        )
        if issue is not None:
            _inc_stat(spider, STAT_ITEMS_REJECTED)
            _inc_stat(spider, _issue_stat(issue))
            _log.warning(
                "pipeline.quality_quarantined",
                product_id=item.product.id,
                issue=issue.value,
                amount=str(amount),
            )
            raise DropItem(f"quality gate {issue.value}: {item.product.id}")
        return item


def _inc_stat(spider: Spider, key: str) -> None:
    """Bump a Scrapy stat if the crawler exposes one (a no-op in bare unit tests)."""
    stats = getattr(getattr(spider, "crawler", None), "stats", None)
    if stats is not None:
        stats.inc_value(key)
