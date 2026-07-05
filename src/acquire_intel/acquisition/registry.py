"""Source registry (stub for T0.4).

Maps a source id to the spider that crawls it. Today it holds only the ``demo``
no-op source; real sources register here as their extractor slices land (T1+).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from acquire_intel.acquisition.spiders.noop import NoOpSpider

if TYPE_CHECKING:
    from scrapy import Spider

_REGISTRY: dict[str, type[Spider]] = {
    "demo": NoOpSpider,
}


def get_spider(source_id: str) -> type[Spider] | None:
    """Return the spider class registered for ``source_id``, or ``None``."""
    return _REGISTRY.get(source_id)


def known_sources() -> list[str]:
    """Return the sorted list of registered source ids."""
    return sorted(_REGISTRY)
