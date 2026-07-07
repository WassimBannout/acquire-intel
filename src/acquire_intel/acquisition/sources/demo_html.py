"""``demo_html`` — a JS-rendered HTML ``SourceExtractor`` (T2.1, ADR-0002, docs/04 §1).

Models a store whose product grid is built client-side: a plain fetch sees an empty page, so
the request is rendered with **Playwright** (via ``scrapy-playwright``) and we wait for the
product nodes before parsing. The extractor owns only source-specific concerns — what to
request and how to turn rendered HTML into ``RawProduct``s (``specs/extractor-interface.md``);
rendering, throttling, backoff, and rotation are shared layers (docs/04 §2, M3).

Selector resilience (docs/04 §1): critical fields hang off stable ``data-*`` hooks, not brittle
class chains. If a redesign moves those hooks (selector drift), the card selector matches
nothing and the extractor **yields nothing** — a rejection the run records — rather than
emitting garbage or fabricating a missing price (ADR-0008, contract rule 3).

The HTML→``RawProduct`` mapping is a pure function (:func:`parse_products`) over a rendered
snapshot, so it is fixture-testable without a browser; Playwright is only the fetch mechanism.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import scrapy
from parsel import Selector
from pydantic import ValidationError
from scrapy_playwright.page import PageMethod

from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.acquisition.telemetry import record_parse
from acquire_intel.monitoring.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from scrapy.http import Response

# RFC-2606 reserved domain: a realistic-looking but non-routable demo target. Real sources
# supply their base URL via source config (the sources registry); never a hardcoded target.
DEMO_HTML_BASE_URL = "https://demo-html.example.com"
# The stable hook a rendered product card is found by (and the wait-for condition).
_CARD_SELECTOR = "[data-product-id]"

_log = get_logger("acquire_intel.acquisition.demo_html")


class DemoHtmlExtractor(scrapy.Spider):
    """A JS-rendered HTML source extractor of ``kind="html"`` (Playwright-backed).

    Implements the ``SourceExtractor`` protocol (``id``/``kind``/``stale_after`` +
    ``start_requests``/``parse``) and is simultaneously a Scrapy ``Spider``. The listing request
    is marked for Playwright and waits for the product grid before the response is parsed.
    """

    id = "demo_html"
    name = "demo_html"
    kind = "html"
    stale_after = timedelta(hours=6)

    def __init__(
        self,
        base_url: str = DEMO_HTML_BASE_URL,
        default_currency: str = "EUR",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.default_currency = default_currency

    def _listing_url(self) -> str:
        return f"{self.base_url}/collections/all"

    def start_requests(self) -> Iterable[scrapy.Request]:
        """Yield the listing request, rendered by Playwright and awaited to hydrate."""
        yield scrapy.Request(
            self._listing_url(),
            callback=self.parse,
            meta={
                "playwright": True,
                "playwright_page_methods": [
                    PageMethod("wait_for_selector", _CARD_SELECTOR),
                ],
            },
        )

    async def start(self) -> Any:
        """Scrapy 2.13+ engine entrypoint — bridges to the protocol's ``start_requests``."""
        for request in self.start_requests():
            yield request

    def parse(self, response: Response, **kwargs: Any) -> Iterable[RawProduct]:
        """Turn the rendered listing into ``RawProduct``s (nothing if selectors drift)."""
        products = parse_products(response.text, base_url=self.base_url)
        # `seen` = product-card containers present; a card found but unmappable (renamed inner
        # fields) is field drift. If the container hook itself drifts, seen == 0 → the volume gate
        # (T3.5) catches it, not this signal (ADR-0014).
        seen = len(Selector(text=response.text).css(_CARD_SELECTOR))
        record_parse(self, seen=seen, mapped=len(products))
        _log.info("demo_html.page_parsed", url=response.url, seen=seen, emitted=len(products))
        yield from products


def parse_products(html: str, *, base_url: str) -> list[RawProduct]:
    """Map a rendered product-grid snapshot to ``RawProduct``s (pure, browser-independent).

    Cards are located by the stable ``data-product-id`` hook; a card missing a required field
    (id/title/price) is skipped, not fabricated. A drifted page whose cards no longer carry the
    hook yields an empty list.
    """
    selector = Selector(text=html)
    products: list[RawProduct] = []
    for card in selector.css(_CARD_SELECTOR):
        raw = _card_to_raw(card, base_url)
        if raw is not None:
            products.append(raw)
    return products


def _card_to_raw(card: Selector, base_url: str) -> RawProduct | None:
    """Map one rendered card to a ``RawProduct``; return ``None`` to skip it."""
    external_id = _clean(card.attrib.get("data-product-id"))
    title = _clean(card.css(".product-card__title::text").get())
    price = _clean(card.css("[data-price]::attr(data-price)").get())
    if external_id is None or title is None or price is None:
        _log.warning("demo_html.item_skipped", external_id=external_id)
        return None

    href = card.css("a.product-card__link::attr(href)").get()
    try:
        return RawProduct(
            external_id=external_id,
            title=title,
            url=urljoin(f"{base_url}/", href) if href else base_url,
            raw_price=price,
            currency=_clean(card.css("[data-currency]::attr(data-currency)").get()),
            in_stock=_parse_stock(card.css("[data-in-stock]::attr(data-in-stock)").get()),
            brand=_clean(card.css(".product-card__brand::text").get()),
            image_url=card.css(".product-card__img::attr(src)").get(),
        )
    except ValidationError as exc:
        _log.warning("demo_html.item_invalid", external_id=external_id, errors=exc.error_count())
        return None


def _clean(value: str | None) -> str | None:
    """Strip whitespace; return ``None`` for missing/blank values."""
    if value is None:
        return None
    text = value.strip()
    return text or None


def _parse_stock(value: str | None) -> bool | None:
    """Map a ``data-in-stock`` attribute to a bool, or ``None`` if absent/unknown."""
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None
