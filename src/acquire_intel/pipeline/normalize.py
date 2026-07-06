"""Normalization: source-native ``RawProduct`` → canonical ``Product`` + ``PriceObservation``.

Pure, Scrapy-independent functions (T1.4, docs/03 §3, ADR-0010). The Scrapy item pipeline
(``item_pipeline.py``) is a thin adapter over these. Rules:

- Canonical product id is ``{source_id}:{external_id}``.
- ``raw_price`` (string or number) parses to a non-negative, finite ``Decimal``.
- Currency resolves from the item, else a source-level default; if neither is present (or it
  is not a 3-letter ISO-4217 code) the item is rejected — never guessed.
- Titles are whitespace-normalized; a title empty after normalization is rejected.
- An unmappable item raises :class:`NormalizationError`; the pipeline drops and counts it and
  nothing garbage is ever stored (ADR-0008).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from acquire_intel.contracts import Money, PriceObservation, Product

if TYPE_CHECKING:
    from datetime import datetime

    from acquire_intel.acquisition.extractor import RawProduct


class NormalizationError(ValueError):
    """A ``RawProduct`` could not be mapped to the canonical model. The item is rejected."""


@dataclass(frozen=True)
class NormalizedItem:
    """The canonical output of normalizing one ``RawProduct``.

    Bundles the upsert projection and the immutable observation the persistence layer (T1.5)
    writes together for a single capture.
    """

    product: Product
    observation: PriceObservation


def canonical_product_id(source_id: str, external_id: str) -> str:
    """The stable cross-source product key: ``{source_id}:{external_id}``."""
    return f"{source_id}:{external_id}"


def parse_price(raw_price: str | int | float) -> Decimal:
    """Parse a source-native price into a non-negative, finite ``Decimal``.

    Numbers are stringified first so binary-float artifacts never enter a money value.
    """
    try:
        amount = Decimal(str(raw_price).strip())
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"unparseable price: {raw_price!r}") from exc
    if not amount.is_finite():
        raise NormalizationError(f"non-finite price: {raw_price!r}")
    if amount < 0:
        raise NormalizationError(f"negative price: {raw_price!r}")
    return amount


def resolve_currency(raw_currency: str | None, default_currency: str | None) -> str:
    """Resolve an ISO-4217 currency from the item, else the source default; else reject.

    A currency is never guessed: if neither source states one, the item is unmappable.
    """
    candidate = (raw_currency or default_currency or "").strip().upper()
    if len(candidate) != 3 or not candidate.isalpha():
        raise NormalizationError(f"missing/invalid ISO-4217 currency: {raw_currency!r}")
    return candidate


def normalize_title(title: str) -> str:
    """Collapse whitespace; reject a title that is empty once normalized."""
    normalized = " ".join(title.split())
    if not normalized:
        raise NormalizationError("empty title after normalization")
    return normalized


def normalize(
    raw: RawProduct,
    *,
    source_id: str,
    run_id: str,
    captured_at: datetime,
    default_currency: str | None = None,
) -> NormalizedItem:
    """Map one ``RawProduct`` to a canonical ``Product`` + ``PriceObservation``.

    Raises :class:`NormalizationError` if the item cannot be mapped (bad price, no currency,
    empty title). ``captured_at`` stamps both the observation (its time-series axis) and the
    product's first/last-seen; the persistence layer preserves the true ``first_seen_at`` on
    upsert (T1.5).
    """
    product_id = canonical_product_id(source_id, raw.external_id)
    amount = parse_price(raw.raw_price)
    currency = resolve_currency(raw.currency, default_currency)
    title = normalize_title(raw.title)

    product = Product(
        id=product_id,
        source_id=source_id,
        external_id=raw.external_id,
        title=title,
        url=raw.url,
        brand=raw.brand,
        image_url=raw.image_url,
        latest_price=Money(amount=amount, currency=currency),
        in_stock=raw.in_stock,
        first_seen_at=captured_at,
        last_seen_at=captured_at,
    )
    observation = PriceObservation(
        product_id=product_id,
        source_id=source_id,
        run_id=run_id,
        amount=amount,
        currency=currency,
        in_stock=raw.in_stock,
        captured_at=captured_at,
    )
    return NormalizedItem(product=product, observation=observation)
