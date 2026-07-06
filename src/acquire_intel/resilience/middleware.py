"""Ban-detection Scrapy downloader middleware (T3.2, ADR-0005, docs/04 §2.5).

Wraps the pure :func:`~acquire_intel.resilience.classifier.classify` as a downloader middleware so
**every** response is labelled before it can reach a spider callback. A non-``ok`` response is
recorded as a ``BanEvent`` (Scrapy stats + a structured log, and appended to the spider's
``ban_events`` sink when present, for the crawl-run ledger in T3.6) and then **dropped** via
``IgnoreRequest`` — the extractor never sees a block/CAPTCHA/empty page, so nothing garbage is ever
parsed or persisted (ADR-0008).

This task performs *detection + gating* only. The recommended recovery action (backoff / rotate)
is recorded on the event as policy; actually executing it — retrying under backoff or a fresh
identity instead of dropping — is layered on in T3.3 (throttle/backoff) and T3.4 (rotation).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from scrapy.exceptions import IgnoreRequest

from acquire_intel.contracts import BanEvent
from acquire_intel.monitoring.logging import get_logger
from acquire_intel.resilience.classifier import (
    Classification,
    ban_kind,
    classify,
    recommended_action,
)

if TYPE_CHECKING:
    from scrapy import Spider
    from scrapy.crawler import Crawler
    from scrapy.http import Request, Response
    from scrapy.statscollectors import StatsCollector

_log = get_logger("acquire_intel.resilience.ban")

STAT_BAN_EVENTS = "acquire/ban_events"


def _stat_for(kind: str) -> str:
    return f"acquire/ban/{kind}"


class BanDetectionMiddleware:
    """Classify every response; record + drop the bans so only ``ok`` responses reach a spider."""

    def __init__(self, stats: StatsCollector | None = None) -> None:
        self.stats = stats

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> BanDetectionMiddleware:
        return cls(stats=crawler.stats)

    def process_response(self, request: Request, response: Response, spider: Spider) -> Response:
        # Never gate infrastructure fetches (e.g. robots.txt), only real crawl responses.
        if request.meta.get("dont_obey_robotstxt"):
            return response

        classification = classify(status=response.status, body=response.body)
        if classification is Classification.OK:
            return response

        self._record(classification, request=request, response=response, spider=spider)
        raise IgnoreRequest(f"ban:{classification.value} for {request.url}")

    def _record(
        self,
        classification: Classification,
        *,
        request: Request,
        response: Response,
        spider: Spider,
    ) -> None:
        event = BanEvent(
            kind=ban_kind(classification),
            action_taken=recommended_action(classification),
            http_status=response.status,
            occurred_at=datetime.now(UTC),
        )
        if self.stats is not None:
            self.stats.inc_value(STAT_BAN_EVENTS)
            self.stats.inc_value(_stat_for(event.kind))

        # Hand the full event to the crawl-run ledger sink if the spider exposes one (T3.6).
        sink = getattr(spider, "ban_events", None)
        if isinstance(sink, list):
            sink.append(event)

        _log.warning(
            "resilience.ban_detected",
            kind=event.kind,
            action=event.action_taken,
            http_status=event.http_status,
            url=request.url,
        )
