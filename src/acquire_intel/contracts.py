"""Canonical domain contracts as pydantic v2 models (T1.2, ADR-0008, docs/03).

These mirror the published JSON Schemas in ``specs/data-contracts/`` — the pydantic models
are the runtime source of truth, the JSON Schemas the language-agnostic published contract,
and a parity test asserts they never diverge. Extractors emit source-native ``RawProduct``
(``acquisition/extractor.py``); the pipeline normalizes into the ``Product`` +
``PriceObservation`` defined here.

Invariants encoded here:
- Money is ``Decimal`` + ISO-4217 ``currency`` — never a bare float (serialized as a string).
- All timestamps are timezone-aware and normalized to UTC.
- Every model is closed (``extra="forbid"``) so a junk/block payload cannot construct.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field


def _to_utc(value: datetime) -> datetime:
    """Normalize a timezone-aware datetime to UTC (naive inputs are rejected upstream)."""
    return value.astimezone(UTC)


# A timezone-aware datetime, normalized to UTC. ``AwareDatetime`` rejects naive datetimes;
# the after-validator pins the zone to UTC so every stored timestamp is comparable.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]

RunStatus = Literal["running", "success", "partial", "failed", "quarantined"]
BanKind = Literal["rate_limited", "blocked", "captcha", "empty"]
BanAction = Literal["backoff", "rotate_identity", "rotate_proxy", "give_up"]


class Money(BaseModel):
    """A monetary amount: a ``Decimal`` amount + ISO-4217 currency. Never a bare float."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal  # serialized as a string; never a float
    currency: str  # ISO-4217


class Product(BaseModel):
    """Canonical product projection (upsert). Rebuildable from observations + latest crawl."""

    model_config = ConfigDict(extra="forbid")

    id: str  # canonical id: {source_id}:{external_id}
    source_id: str
    external_id: str
    title: str = Field(min_length=1)
    url: str
    brand: str | None = None
    image_url: str | None = None
    latest_price: Money | None = None
    in_stock: bool | None = None
    first_seen_at: UtcDatetime
    last_seen_at: UtcDatetime


class PriceObservation(BaseModel):
    """One immutable price capture — the append-only time-series (axis: ``captured_at``)."""

    model_config = ConfigDict(extra="forbid")

    product_id: str
    source_id: str
    run_id: str  # owning crawl run
    amount: Decimal  # Decimal, never a float
    currency: str  # ISO-4217
    in_stock: bool | None = None
    captured_at: UtcDatetime  # UTC capture time (time-series axis)


class BanEvent(BaseModel):
    """One detected block/rate-limit/CAPTCHA/empty response and the action taken."""

    model_config = ConfigDict(extra="forbid")

    kind: BanKind
    action_taken: BanAction
    http_status: int | None = None
    occurred_at: UtcDatetime


class CrawlRun(BaseModel):
    """One collection attempt for a source: audit trail + health, including ban events."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source_id: str
    status: RunStatus
    started_at: UtcDatetime
    items_ok: int = Field(default=0, ge=0)
    items_rejected: int = Field(default=0, ge=0)
    ban_events: list[BanEvent] = Field(default_factory=list)
    timings: dict[str, Any] = Field(default_factory=dict)
    finished_at: UtcDatetime | None = None
