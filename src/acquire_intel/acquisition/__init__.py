"""acquisition: the acquisition engine.

Hosts the Scrapy project, spiders, and pluggable ``SourceExtractor`` implementations
of kind html/rest/graphql (ADR-0002, ADR-0003).
"""

from acquire_intel.acquisition.registry import get_spider, known_sources
from acquire_intel.acquisition.runner import run_crawl

__all__ = ["get_spider", "known_sources", "run_crawl"]
