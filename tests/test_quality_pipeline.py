"""Quality-gate pipeline adapters (T3.5, ADR-0012).

Two layers:
- the per-item ``QualityGatePipeline`` drops out-of-range / discontinuous items (no DB needed);
- the run-atomic volume gate in ``PersistencePipeline`` quarantines a whole run — committing
  **nothing** — when its surviving count strays from the source's baseline (DB integration).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from scrapy.exceptions import DropItem
from scrapy.settings import Settings
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.acquisition.runner import _run_status
from acquire_intel.config import ConfigError
from acquire_intel.pipeline.normalize import NormalizedItem, normalize
from acquire_intel.pipeline.persistence import STAT_QUALITY_QUARANTINED, PersistencePipeline
from acquire_intel.pipeline.quality import GateThresholds, QualityGatePipeline
from acquire_intel.storage import (
    CrawlRunRepository,
    ProductRepository,
    Source,
    SourceRepository,
    get_engine,
    new_session,
    session_scope,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

_SOURCE_ID = "demo_rest"


class _FakeStats:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def inc_value(self, key: str, count: int = 1, start: int = 0) -> None:
        self.counts[key] = self.counts.get(key, start) + count


def _item(external_id: str, price: str, *, run_id: str = "run") -> NormalizedItem:
    raw = RawProduct(
        external_id=external_id,
        title=f"Product {external_id}",
        url=f"https://shop.example.com/p/{external_id}",
        raw_price=price,
        currency="USD",
    )
    return normalize(
        raw,
        source_id=_SOURCE_ID,
        run_id=run_id,
        captured_at=datetime.now(UTC),
        default_currency="USD",
    )


def _spider(stats: _FakeStats, *, run_id: str = "run") -> Any:
    return SimpleNamespace(
        name=_SOURCE_ID,
        id=_SOURCE_ID,
        kind="rest",
        run_id=run_id,
        crawler=SimpleNamespace(stats=stats, settings=Settings({})),
    )


# --- per-item gates (no DB) ------------------------------------------------------------------


def _gate(prev: dict[str, Decimal], thresholds: GateThresholds) -> QualityGatePipeline:
    """A ``QualityGatePipeline`` with preloaded priors, bypassing the DB in ``open_spider``."""
    pipe = QualityGatePipeline()
    pipe.enabled = True
    pipe.source_id = _SOURCE_ID
    pipe.thresholds = thresholds
    pipe._prev_prices = prev
    return pipe


def test_quality_gate_passes_a_plausible_continuous_item() -> None:
    stats = _FakeStats()
    pipe = _gate({"demo_rest:1": Decimal("40")}, GateThresholds(price_max=Decimal("1000")))
    item = _item("1", "44.00")
    assert pipe.process_item(item, _spider(stats)) is item
    assert stats.counts == {}


def test_quality_gate_drops_an_out_of_range_price() -> None:
    stats = _FakeStats()
    pipe = _gate({}, GateThresholds(price_max=Decimal("1000")))
    with pytest.raises(DropItem):
        pipe.process_item(_item("1", "50000"), _spider(stats))
    assert stats.counts.get("acquire/quality/out_of_range") == 1
    assert stats.counts.get("acquire/items_rejected") == 1


def test_quality_gate_drops_a_discontinuous_price() -> None:
    stats = _FakeStats()
    # Prior $10, new $500 → 50x jump, beyond the default 10x ratio.
    pipe = _gate({"demo_rest:1": Decimal("10")}, GateThresholds(max_jump_ratio=10.0))
    with pytest.raises(DropItem):
        pipe.process_item(_item("1", "500"), _spider(stats))
    assert stats.counts.get("acquire/quality/discontinuous") == 1


def test_quality_gate_ignores_non_normalized_items() -> None:
    pipe = _gate({}, GateThresholds())
    sentinel = object()
    assert pipe.process_item(sentinel, _spider(_FakeStats())) is sentinel


# --- run status mapping (no DB) --------------------------------------------------------------


def test_run_status_maps_a_volume_quarantine() -> None:
    assert _run_status("finished", 0, 1) == "quarantined"
    # Quarantine wins even if some items were also per-item rejected.
    assert _run_status("finished", 3, 1) == "quarantined"
    assert _run_status("finished", 0, 0) == "success"
    assert _run_status("finished", 2, 0) == "partial"


# --- volume gate (DB integration) ------------------------------------------------------------

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


@pytest.fixture
def clean_db(engine: Engine) -> Iterator[None]:
    def _truncate() -> None:
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))

    _truncate()
    try:
        yield
    finally:
        _truncate()


def _seed_source_and_runs(*, baseline: int, current_run_id: str) -> None:
    now = datetime.now(UTC)
    with session_scope() as s:
        SourceRepository(s).add(
            Source(
                id=_SOURCE_ID,
                kind="rest",
                base_url="https://shop.example.com",
                stale_after_seconds=21600,
                crawl_policy={"default_currency": "USD"},
            )
        )
    with session_scope() as s:
        CrawlRunRepository(s).open(run_id="baseline_run", source_id=_SOURCE_ID, started_at=now)
    with session_scope() as s:
        CrawlRunRepository(s).close(
            "baseline_run", status="success", items_ok=baseline, items_rejected=0, finished_at=now
        )
    with session_scope() as s:
        CrawlRunRepository(s).open(run_id=current_run_id, source_id=_SOURCE_ID, started_at=now)


@pytest.mark.integration
def test_volume_anomaly_quarantines_the_run_and_commits_nothing(clean_db: None) -> None:
    # Baseline 10; a run of only 2 survivors is a >50% collapse → quarantine, store nothing.
    _seed_source_and_runs(baseline=10, current_run_id="run_now")
    stats = _FakeStats()
    spider = _spider(stats, run_id="run_now")

    pipe = PersistencePipeline()
    pipe.open_spider(spider)
    assert pipe.baseline == 10
    for i in range(2):
        pipe.process_item(_item(str(i), "19.99", run_id="run_now"), spider)
    pipe.close_spider(spider)

    assert stats.counts.get(STAT_QUALITY_QUARANTINED) == 1
    assert pipe.persisted == 0
    reader = new_session()
    try:
        assert ProductRepository(reader).count() == 0  # nothing garbage stored
    finally:
        reader.close()


@pytest.mark.integration
def test_within_tolerance_run_commits_normally(clean_db: None) -> None:
    # Baseline 6; a run of 5 survivors is within ±50% [3, 9] → commit all.
    _seed_source_and_runs(baseline=6, current_run_id="run_now")
    stats = _FakeStats()
    spider = _spider(stats, run_id="run_now")

    pipe = PersistencePipeline()
    pipe.open_spider(spider)
    for i in range(5):
        pipe.process_item(_item(str(i), "19.99", run_id="run_now"), spider)
    pipe.close_spider(spider)

    assert STAT_QUALITY_QUARANTINED not in stats.counts
    assert pipe.persisted == 5
    reader = new_session()
    try:
        assert ProductRepository(reader).count() == 5
    finally:
        reader.close()
