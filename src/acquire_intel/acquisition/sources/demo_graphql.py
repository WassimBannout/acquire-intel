"""``demo_graphql`` — a cursor-paginated GraphQL ``SourceExtractor`` (T2.2, ADR-0004, docs/04 §1).

Models a Shopify **Storefront API**-style endpoint: products are a Relay connection queried
with a typed operation carrying ``$first``/``$after`` variables, and pagination walks the
``pageInfo { hasNextPage endCursor }`` cursor until ``hasNextPage`` is false. Each request is a
JSON ``POST`` of ``{query, variables}`` — the GraphQL-specific concerns (query construction,
variables, cursor pagination) this kind exists to showcase (docs/04 §1).

Query derivation (per ADR-0004 follow-up): the operation below is derived from the **public
Shopify Storefront API docs** for ``QueryRoot.products`` (a ``ProductConnection``) — not from a
live introspection dump. A real source's query is derived the same way (public schema docs) or
by an authorized introspection query; either way the query is checked in, versioned, and
fixture-tested so drift is caught.

The extractor owns **only** source-specific concerns — what to request and how to turn a
response into ``RawProduct``s (``specs/extractor-interface.md``). Throttling, backoff, retry,
proxy/identity rotation, and ban detection are shared resilience layers applied uniformly by the
downloader middlewares (docs/04 §2, wired in M3); this module contains none of that.

Robustness contract (ADR-0008): a response that is not the expected ``{"data": {"products":
{...}}}`` envelope — a GraphQL ``errors`` payload, a block/CAPTCHA page, non-JSON, or the wrong
shape — yields **nothing** and stops paging; a single node missing a required field is skipped,
never fabricated. Rejections are surfaced for the pipeline/crawl-run ledger to count.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import scrapy
from pydantic import ValidationError
from scrapy.http import JsonRequest, TextResponse

from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.monitoring.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from scrapy.http import Response

# RFC-2606 reserved domain: a realistic-looking but non-routable demo target. Real sources
# supply their base URL via source config (the sources registry); never a hardcoded target.
DEMO_GRAPHQL_BASE_URL = "https://graphql.example.com"
# Storefront GraphQL endpoints are versioned; the path is a source detail, not a global const.
_GRAPHQL_PATH = "/api/2024-01/graphql.json"
_DEFAULT_PAGE_SIZE = 50  # Storefront connections cap at 250; 50 is a polite default.

# Typed operation with a Relay-connection shape (docs: QueryRoot.products → ProductConnection).
# ``$first``/``$after`` drive forward cursor pagination; only the fields we map are requested.
_PRODUCTS_QUERY = """
query Products($first: Int!, $after: String) {
  products(first: $first, after: $after) {
    edges {
      cursor
      node {
        id
        title
        handle
        vendor
        availableForSale
        featuredImage { url }
        priceRange { minVariantPrice { amount currencyCode } }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
""".strip()

_log = get_logger("acquire_intel.acquisition.demo_graphql")


class DemoGraphqlExtractor(scrapy.Spider):
    """A cursor-paginated GraphQL source extractor of ``kind="graphql"``.

    Implements the ``SourceExtractor`` protocol (``id``/``kind``/``stale_after`` +
    ``start_requests``/``parse``) and is simultaneously a Scrapy ``Spider`` so the engine can
    drive it. Each request is a JSON ``POST`` of the typed query + variables; pagination is
    followed via ``pageInfo.endCursor`` and kept inside the Scrapy engine so the shared
    resilience layer stays in force.
    """

    id = "demo_graphql"
    name = "demo_graphql"
    kind = "graphql"
    stale_after = timedelta(hours=6)

    def __init__(
        self,
        base_url: str = DEMO_GRAPHQL_BASE_URL,
        page_size: int = _DEFAULT_PAGE_SIZE,
        default_currency: str = "USD",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        # Storefront states a per-node ``currencyCode``; this fallback is only used when a node
        # omits it, applied during normalization (ADR-0010). Real sources supply it via config.
        self.default_currency = default_currency

    # --- request construction ------------------------------------------------

    @property
    def _endpoint(self) -> str:
        return f"{self.base_url}{_GRAPHQL_PATH}"

    def _graphql_request(self, after: str | None) -> JsonRequest:
        """Build a typed GraphQL ``POST`` for one page (``after=None`` for the first)."""
        variables: dict[str, Any] = {"first": self.page_size, "after": after}
        return JsonRequest(
            url=self._endpoint,
            data={"query": _PRODUCTS_QUERY, "variables": variables},
            callback=self.parse,
        )

    def start_requests(self) -> Iterable[scrapy.Request]:
        """Yield the first page; later pages are followed from :meth:`parse` via the cursor."""
        yield self._graphql_request(after=None)

    async def start(self) -> Any:
        """Scrapy 2.13+ engine entrypoint — bridges to the protocol's ``start_requests``."""
        for request in self.start_requests():
            yield request

    # --- parsing -------------------------------------------------------------

    def parse(self, response: Response, **kwargs: Any) -> Iterable[RawProduct | scrapy.Request]:
        """Turn a GraphQL page into ``RawProduct``s and follow the cursor.

        A response that is not the expected ``{"data": {"products": {...}}}`` envelope (a
        GraphQL ``errors`` payload, block page, empty body, or wrong shape) yields nothing and
        stops paging.
        """
        connection = self._extract_connection(response)
        if connection is None:
            return

        edges = [e for e in connection.get("edges", []) if isinstance(e, dict)]
        emitted = 0
        for edge in edges:
            node = edge.get("node")
            if not isinstance(node, dict):
                continue
            raw = self._to_raw_product(node)
            if raw is not None:
                emitted += 1
                yield raw

        page_info = connection.get("pageInfo")
        page_info = page_info if isinstance(page_info, dict) else {}
        _log.info("demo_graphql.page_parsed", seen=len(edges), emitted=emitted)

        # Follow the forward cursor only while the connection says there is more.
        if page_info.get("hasNextPage") and page_info.get("endCursor"):
            yield self._graphql_request(after=str(page_info["endCursor"]))

    def _extract_connection(self, response: Response) -> dict[str, Any] | None:
        """Return the ``products`` connection dict, or ``None`` if the envelope is unexpected."""
        if not isinstance(response, TextResponse):
            # A non-text (e.g. binary) response is never a JSON GraphQL page.
            _log.warning("demo_graphql.non_text_response", url=response.url)
            return None
        try:
            payload = response.json()
        except ValueError:
            # Non-JSON body — e.g. an HTML block/challenge page. Never parsed as data.
            _log.warning("demo_graphql.non_json_response", url=response.url)
            return None
        if not isinstance(payload, dict):
            _log.warning("demo_graphql.unexpected_shape", url=response.url)
            return None
        # GraphQL surfaces failures in ``errors``; treat any as a rejected page (never partial).
        if payload.get("errors"):
            _log.warning("demo_graphql.graphql_errors", url=response.url)
            return None
        data = payload.get("data")
        connection = data.get("products") if isinstance(data, dict) else None
        if not isinstance(connection, dict) or not isinstance(connection.get("edges"), list):
            _log.warning("demo_graphql.unexpected_shape", url=response.url)
            return None
        return connection

    def _to_raw_product(self, node: dict[str, Any]) -> RawProduct | None:
        """Map one GraphQL product node to a ``RawProduct``; return ``None`` to skip it.

        Missing/blank required fields cause a skip (counted as a rejection downstream) rather
        than a fabricated default — the extractor never emits garbage (ADR-0008).
        """
        external_id = self._stringify(node.get("id"))
        amount, currency = self._min_price(node.get("priceRange"))
        if external_id is None or amount is None:
            _log.warning("demo_graphql.item_skipped", id=node.get("id"))
            return None

        handle = node.get("handle")
        try:
            return RawProduct(
                external_id=external_id,
                title=node.get("title", ""),  # blank title is rejected by the model
                url=f"{self.base_url}/products/{handle}" if handle else self.base_url,
                raw_price=amount,
                currency=currency,  # Storefront states a per-node currencyCode
                in_stock=self._as_bool(node.get("availableForSale")),
                brand=node.get("vendor"),
                image_url=self._image_url(node.get("featuredImage")),
                extra={"handle": handle} if handle else {},
            )
        except ValidationError as exc:
            _log.warning("demo_graphql.item_invalid", id=node.get("id"), errors=exc.error_count())
            return None

    # --- field helpers -------------------------------------------------------

    @staticmethod
    def _stringify(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _min_price(price_range: Any) -> tuple[str | None, str | None]:
        """Return ``(amount, currencyCode)`` from ``priceRange.minVariantPrice`` (or ``None``s)."""
        if not isinstance(price_range, dict):
            return None, None
        money = price_range.get("minVariantPrice")
        if not isinstance(money, dict) or money.get("amount") is None:
            return None, None
        amount = str(money["amount"]).strip() or None
        currency = money.get("currencyCode")
        currency = str(currency).strip() if currency else None
        return amount, (currency or None)

    @staticmethod
    def _as_bool(value: Any) -> bool | None:
        return bool(value) if isinstance(value, bool) else None

    @staticmethod
    def _image_url(featured_image: Any) -> str | None:
        if isinstance(featured_image, dict) and featured_image.get("url"):
            return str(featured_image["url"])
        return None
