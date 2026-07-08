"""Source registry stub tests (T0.4)."""

from __future__ import annotations

from acquire_intel.acquisition import get_spider, known_sources
from acquire_intel.acquisition.sources.demo_rest import DemoRestExtractor
from acquire_intel.acquisition.sources.live_rest import LiveRestExtractor
from acquire_intel.acquisition.spiders.noop import NoOpSpider


def test_demo_source_resolves_to_noop_spider() -> None:
    assert get_spider("demo") is NoOpSpider


def test_unknown_source_returns_none() -> None:
    assert get_spider("does_not_exist") is None


def test_known_sources_lists_demo() -> None:
    assert "demo" in known_sources()
    assert known_sources() == sorted(known_sources())


def test_live_rest_is_registered() -> None:
    assert "live_rest" in known_sources()
    assert get_spider("live_rest") is LiveRestExtractor


def test_live_rest_has_a_distinct_source_id_from_demo() -> None:
    # The canonical product id is ``{id}:{external_id}`` keyed on the extractor's ``id`` — a shared
    # id would file a real store's products under ``demo_rest`` and mix live data with the mock.
    assert LiveRestExtractor.id == "live_rest"
    assert LiveRestExtractor.id != DemoRestExtractor.id
    assert LiveRestExtractor.kind == "rest"  # same generic Shopify products.json path
