"""API response models — the serialization contract for the read surface (T1.6).

These pydantic models mirror ``specs/openapi.yaml`` (``ProductsResponse``,
``PriceHistoryResponse``) and are the runtime shape guarantee: routes build them from the
ORM and dump ``by_alias`` so the JSON is camelCase, ``Money.amount`` is a **string** (never a
float), and every data response carries freshness (``dataAsOf`` + ``stale``) plus per-
observation ``capturedAt`` + ``sourceId``. They are the API projection of the canonical
``acquire_intel.contracts`` models — a distinct, camelCase, nested shape — not the same class.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    """Base: snake_case fields, camelCase JSON aliases, constructible by field name."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class MoneyOut(_CamelModel):
    """A monetary amount serialized as ``{amount: string, currency}`` (never a float)."""

    amount: str  # Decimal rendered as a string to avoid float error
    currency: str  # ISO-4217


class Freshness(_CamelModel):
    """Per-response freshness envelope shared by every data endpoint."""

    data_as_of: datetime  # dataAsOf: the most recent data timestamp in the response
    stale: bool  # data_as_of age exceeds the source's stale_after budget


class ProductOut(_CamelModel):
    """A collected product (latest state); ``latest_price``/``in_stock`` derived at query."""

    id: str  # canonical id: {source_id}:{external_id}
    source_id: str
    title: str
    brand: str | None = None
    url: str
    image_url: str | None = None
    latest_price: MoneyOut | None = None  # from the latest observation
    in_stock: bool | None = None  # from the latest observation
    last_seen_at: datetime


class ProductsResponse(Freshness):
    """``GET /products`` body: freshness + the product list."""

    data: list[ProductOut]


class PriceObservationOut(_CamelModel):
    """One point on the price-history axis (append-only)."""

    captured_at: datetime
    source_id: str
    price: MoneyOut
    in_stock: bool | None = None


class PriceHistoryResponse(Freshness):
    """``GET /products/{id}/price-history`` body: freshness + the observation series."""

    product_id: str
    observations: list[PriceObservationOut]


class DealOut(_CamelModel):
    """A product whose latest price dropped from its recent high (``GET /deals``)."""

    product: ProductOut
    previous_price: MoneyOut  # the recent high
    current_price: MoneyOut  # the latest price
    drop_pct: float  # percent below the recent high
    since: datetime  # when the product was at that high


class DealsResponse(Freshness):
    """``GET /deals`` body: freshness + deals ranked by drop magnitude."""

    data: list[DealOut]


class SourceHealthOut(_CamelModel):
    """Per-source collection health (``specs/openapi.yaml`` ``SourceHealth``, T4.4)."""

    source: str
    status: str  # healthy | degraded | stale | failing
    last_success_at: datetime | None = None
    last_run_status: str | None = None  # the latest run's terminal status
    ban_rate: float | None = None  # recent ban events / requests
    stale_after_seconds: int


class SourceHealthResponse(_CamelModel):
    """``GET /health/sources`` body: an overall rollup + per-source health."""

    overall: str  # healthy | degraded | stale | failing
    sources: list[SourceHealthOut]


class CrawlRunOut(_CamelModel):
    """A crawl-run ledger row (``specs/openapi.yaml`` ``CrawlRun``, T4.5)."""

    id: str
    source: str
    status: str  # running | success | partial | failed | quarantined | flagged
    items_ok: int | None = None
    items_rejected: int | None = None
    ban_events: int | None = None
    started_at: datetime
    finished_at: datetime | None = None


class CrawlAcceptedResponse(_CamelModel):
    """``POST /admin/crawl`` 202 body: the launched (``running``) runs."""

    accepted: bool
    runs: list[CrawlRunOut]
