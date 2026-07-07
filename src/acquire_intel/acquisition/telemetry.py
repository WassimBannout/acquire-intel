"""Acquisition telemetry: per-parse counts that feed drift detection (T4.2, FR-16).

Extractors call :func:`record_parse` once per page with how many item-shaped entries they saw
versus how many they successfully mapped to a ``RawProduct``. The cumulative Scrapy stats let the
runner spot **selector/field drift** — a source whose envelope is intact but whose items no longer
map (renamed fields) — and flag the run instead of silently recording a near-empty crawl.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scrapy import Spider

STAT_ENTRIES_SEEN = "acquire/entries_seen"
STAT_ENTRIES_MAPPED = "acquire/entries_mapped"


def record_parse(spider: Spider, *, seen: int, mapped: int) -> None:
    """Add a page's entry counts to the crawl stats (a no-op when there is no stats collector)."""
    stats = getattr(getattr(spider, "crawler", None), "stats", None)
    if stats is None:
        return
    stats.inc_value(STAT_ENTRIES_SEEN, seen)
    stats.inc_value(STAT_ENTRIES_MAPPED, mapped)
