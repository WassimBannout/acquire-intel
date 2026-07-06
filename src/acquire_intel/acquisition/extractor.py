"""The ``SourceExtractor`` contract and its source-native output model (T1.1).

A *source* is any place we collect product/price data from. Each source is one
``SourceExtractor`` of a ``kind`` (html/rest/graphql) that owns **only** source-specific
concerns — *what to request* and *how to turn a response into ``RawProduct``s*. Proxy
rotation, throttling, retries, validation, and storage are shared layers, never the
extractor's job (``specs/extractor-interface.md``, ADR-0003).

``RawProduct`` mirrors ``specs/data-contracts/raw-product.schema.json``; the published JSON
Schema is the contract and this pydantic model is the runtime source of truth. A parity test
asserts they never diverge (ADR-0008).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import timedelta

    from scrapy import Request
    from scrapy.http import Response


class RawProduct(BaseModel):
    """Source-native extractor output, before normalization.

    Emitted by a ``SourceExtractor`` and normalized by the pipeline into a canonical
    ``Product`` + ``PriceObservation`` (Decimal money, canonical id, UTC ``captured_at``).
    Unknown keys are **rejected** (``extra="forbid"``) so a block/CAPTCHA/empty payload
    cannot masquerade as a product; genuinely source-specific fields go in ``extra``.
    Mirrors ``raw-product.schema.json``.
    """

    model_config = ConfigDict(extra="forbid")

    external_id: str  # the source's own id / sku / handle
    title: str = Field(min_length=1)
    url: str
    raw_price: str | int | float  # source-native; normalized to Decimal by the pipeline
    currency: str | None = None  # ISO-4217, if the source states it
    in_stock: bool | None = None
    brand: str | None = None
    image_url: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)  # anything source-specific


@runtime_checkable
class SourceExtractor(Protocol):
    """The single extension point for adding a data source (ADR-0003).

    One module per source implements this protocol and registers itself in the source
    registry with its per-source config. See ``specs/extractor-interface.md`` for the full
    contract and rules (kind-appropriate requests, no cross-layer concerns, never emit
    garbage, pagination via follow-up requests).
    """

    id: str  # unique, stable, e.g. "demo_rest"
    kind: Literal["html", "rest", "graphql"]
    stale_after: timedelta  # freshness budget for this source

    def start_requests(self) -> Iterable[Request]:
        """Yield the initial requests (list / search / paginated entry points)."""
        ...

    def parse(self, response: Response) -> Iterable[RawProduct | Request]:
        """Turn a (already classified-as-not-banned) response into ``RawProduct``s.

        May also yield follow-up ``Request``s for pagination. MUST NOT return partial or
        fabricated data: if the expected shape is absent, yield nothing and let the pipeline
        record a rejection; raise only on unexpected internal errors.
        """
        ...
