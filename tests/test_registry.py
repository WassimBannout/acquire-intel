"""Source registry stub tests (T0.4)."""

from __future__ import annotations

from acquire_intel.acquisition import get_spider, known_sources
from acquire_intel.acquisition.spiders.noop import NoOpSpider


def test_demo_source_resolves_to_noop_spider() -> None:
    assert get_spider("demo") is NoOpSpider


def test_unknown_source_returns_none() -> None:
    assert get_spider("does_not_exist") is None


def test_known_sources_lists_demo() -> None:
    assert "demo" in known_sources()
    assert known_sources() == sorted(known_sources())
