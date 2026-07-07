"""``demo_rest`` — a paginated JSON/REST ``SourceExtractor`` (T1.3, ADR-0004, docs/04 §1).

Models a Shopify-style ``products.json`` endpoint (the REST candidate in PRD open-question 1):
a page is ``{"products": [ {id, title, handle, vendor, variants[], images[]}, ... ]}`` and
pagination walks ``?page=N`` until a page comes back empty.

The extractor owns **only** source-specific concerns — what to request and how to turn a
response into ``RawProduct``s (``specs/extractor-interface.md``). Throttling, backoff, retry,
proxy/identity rotation, and ban detection are shared resilience layers applied uniformly by
the downloader middlewares (docs/04 §2, wired in M3); this module contains none of that.

Robustness contract (ADR-0008): a malformed/blocked page (not the expected JSON envelope)
yields **nothing**, and any single product missing a required field is skipped — never a
fabricated default. Rejections are surfaced for the pipeline/crawl-run ledger to count.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import scrapy
from pydantic import ValidationError
from scrapy.http import TextResponse

from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.acquisition.telemetry import record_parse
from acquire_intel.monitoring.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from scrapy.http import Response

# RFC-2606 reserved domain: a realistic-looking but non-routable demo target. Real sources
# supply their base URL via source config/env (T1.7); never a hardcoded production target.
DEMO_REST_BASE_URL = "https://shop.example.com"
_DEFAULT_PAGE_SIZE = 250  # Shopify products.json caps at 250/page

_log = get_logger("acquire_intel.acquisition.demo_rest")


class DemoRestExtractor(scrapy.Spider):
    """A paginated JSON/REST source extractor of ``kind="rest"``.

    Implements the ``SourceExtractor`` protocol (``id``/``kind``/``stale_after`` +
    ``start_requests``/``parse``) and is simultaneously a Scrapy ``Spider`` so the engine can
    drive it. Scrapy's async ``start`` entrypoint bridges to the protocol's ``start_requests``.
    """

    id = "demo_rest"
    name = "demo_rest"
    kind = "rest"
    stale_after = timedelta(hours=6)

    def __init__(
        self,
        base_url: str = DEMO_REST_BASE_URL,
        page_size: int = _DEFAULT_PAGE_SIZE,
        default_currency: str = "USD",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        # products.json states no per-item currency; the shop-level currency (source config)
        # is applied during normalization (ADR-0010). Real sources supply this via config.
        self.default_currency = default_currency

    # --- request construction ------------------------------------------------

    def _page_url(self, page: int) -> str:
        return f"{self.base_url}/products.json?limit={self.page_size}&page={page}"

    def start_requests(self) -> Iterable[scrapy.Request]:
        """Yield the first page; subsequent pages are followed from :meth:`parse`."""
        yield scrapy.Request(self._page_url(1), callback=self.parse, meta={"page": 1})

    async def start(self) -> Any:
        """Scrapy 2.13+ engine entrypoint — bridges to the protocol's ``start_requests``."""
        for request in self.start_requests():
            yield request

    # --- parsing -------------------------------------------------------------

    def parse(self, response: Response, **kwargs: Any) -> Iterable[RawProduct | scrapy.Request]:
        """Turn a page of JSON into ``RawProduct``s and follow pagination.

        A response that is not the expected ``{"products": [...]}`` envelope (a block page,
        CAPTCHA, empty body, or JSON of the wrong shape) yields nothing and stops paging.
        """
        page = int(response.meta.get("page", 1))
        products = self._extract_product_list(response, page)
        if not products:
            return

        emitted = 0
        for entry in products:
            raw = self._to_raw_product(entry, page)
            if raw is not None:
                emitted += 1
                yield raw

        record_parse(self, seen=len(products), mapped=emitted)
        _log.info("demo_rest.page_parsed", page=page, seen=len(products), emitted=emitted)

        # Follow-up page: a non-empty page implies there may be another (Shopify semantics).
        # Pagination via a follow-up Request keeps the shared resilience layer in force.
        yield scrapy.Request(self._page_url(page + 1), callback=self.parse, meta={"page": page + 1})

    def _extract_product_list(self, response: Response, page: int) -> list[dict[str, Any]]:
        """Return the ``products`` array, or ``[]`` if the envelope is not as expected."""
        if not isinstance(response, TextResponse):
            # A non-text (e.g. binary) response is never a JSON product page.
            _log.warning("demo_rest.non_text_response", page=page, url=response.url)
            return []
        try:
            payload = response.json()
        except ValueError:
            # Non-JSON body — e.g. an HTML block/challenge page. Never parsed as data.
            _log.warning("demo_rest.non_json_response", page=page, url=response.url)
            return []
        if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
            _log.warning("demo_rest.unexpected_shape", page=page, url=response.url)
            return []
        return [entry for entry in payload["products"] if isinstance(entry, dict)]

    def _to_raw_product(self, entry: dict[str, Any], page: int) -> RawProduct | None:
        """Map one source product dict to a ``RawProduct``; return ``None`` to skip it.

        Missing/blank required fields cause a skip (counted as a rejection downstream) rather
        than a fabricated default — the extractor never emits garbage (ADR-0008).
        """
        external_id = self._stringify(entry.get("id"))
        handle = entry.get("handle")
        price = self._first_variant_price(entry.get("variants"))
        if external_id is None or price is None:
            _log.warning("demo_rest.item_skipped", page=page, id=entry.get("id"))
            return None

        try:
            return RawProduct(
                external_id=external_id,
                title=entry.get("title", ""),  # blank title is rejected by the model
                url=f"{self.base_url}/products/{handle}" if handle else self.base_url,
                raw_price=price,
                currency=None,  # products.json doesn't state currency (shop-level)
                in_stock=self._any_available(entry.get("variants")),
                brand=entry.get("vendor"),
                image_url=self._first_image(entry.get("images")),
                extra={"handle": handle} if handle else {},
            )
        except ValidationError as exc:
            _log.warning(
                "demo_rest.item_invalid", page=page, id=entry.get("id"), errors=exc.error_count()
            )
            return None

    # --- field helpers -------------------------------------------------------

    @staticmethod
    def _stringify(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _first_variant_price(variants: Any) -> str | None:
        if not isinstance(variants, list):
            return None
        for variant in variants:
            if isinstance(variant, dict) and variant.get("price") is not None:
                price = str(variant["price"]).strip()
                if price:
                    return price
        return None

    @staticmethod
    def _any_available(variants: Any) -> bool | None:
        if not isinstance(variants, list) or not variants:
            return None
        return any(isinstance(v, dict) and bool(v.get("available")) for v in variants)

    @staticmethod
    def _first_image(images: Any) -> str | None:
        if isinstance(images, list):
            for image in images:
                if isinstance(image, dict) and image.get("src"):
                    return str(image["src"])
        return None
