"""A no-op spider: opens and closes a crawl cleanly without emitting requests.

Used by T0.4 to prove the crawl wiring (CLI → registry → Scrapy → structured run
log) end-to-end before any real source exists.
"""

from __future__ import annotations

from typing import Any

import scrapy


class NoOpSpider(scrapy.Spider):
    """Yields no requests; the crawl runs to completion immediately."""

    name = "noop"

    async def start(self) -> Any:
        """Emit nothing (empty async generator)."""
        no_requests: tuple[Any, ...] = ()
        for request in no_requests:  # keeps this an async generator that yields nothing
            yield request
