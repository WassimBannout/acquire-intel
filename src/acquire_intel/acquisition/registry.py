"""Source registry.

Maps a source id to the spider/extractor that crawls it. Holds the ``demo`` no-op
source (T0.4) and real ``SourceExtractor`` sources as their slices land (T1+).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from acquire_intel.acquisition.sources.demo_html import DemoHtmlExtractor
from acquire_intel.acquisition.sources.demo_rest import DemoRestExtractor
from acquire_intel.acquisition.spiders.noop import NoOpSpider

if TYPE_CHECKING:
    from scrapy import Spider

_REGISTRY: dict[str, type[Spider]] = {
    "demo": NoOpSpider,
    "demo_rest": DemoRestExtractor,
    "demo_html": DemoHtmlExtractor,
}


def get_spider(source_id: str) -> type[Spider] | None:
    """Return the spider class registered for ``source_id``, or ``None``."""
    return _REGISTRY.get(source_id)


def known_sources() -> list[str]:
    """Return the sorted list of registered source ids."""
    return sorted(_REGISTRY)
