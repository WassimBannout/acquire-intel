"""Pipeline: validate → normalize → dedup (T1.4, ADR-0008/0010).

Covers the pure normalization functions (mapping correctness + rejection of unmappable
items) and the Scrapy ``NormalizePipeline`` adapter (boundary validation, reject counting,
in-run dedup).
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.contracts import PriceObservation, Product
from acquire_intel.pipeline.item_pipeline import NormalizePipeline
from acquire_intel.pipeline.normalize import (
    NormalizationError,
    NormalizedItem,
    canonical_product_id,
    normalize,
    parse_price,
    resolve_currency,
)

try:
    from scrapy.exceptions import DropItem
except ImportError:  # pragma: no cover
    DropItem = Exception  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from typing import Any

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "demo_rest"
_AT = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def _raw(**overrides: Any) -> RawProduct:
    base: dict[str, Any] = {
        "external_id": "sku1",
        "title": "Widget",
        "url": "https://shop.example.com/products/widget",
        "raw_price": "19.99",
        "currency": "USD",
    }
    base.update(overrides)
    return RawProduct(**base)


def _normalize(raw: RawProduct, **kw: Any) -> NormalizedItem:
    params: dict[str, Any] = {
        "source_id": "demo_rest",
        "run_id": "run-1",
        "captured_at": _AT,
    }
    params.update(kw)
    return normalize(raw, **params)


# --- pure helpers -------------------------------------------------------------


def test_canonical_product_id() -> None:
    assert canonical_product_id("demo_rest", "7001") == "demo_rest:7001"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("19.99", Decimal("19.99")),
        (20, Decimal("20")),
        (19.99, Decimal("19.99")),
        (" 5.00 ", Decimal("5.00")),
    ],
)
def test_parse_price_valid(value: str | int | float, expected: Decimal) -> None:
    assert parse_price(value) == expected


@pytest.mark.parametrize("value", ["", "free", "N/A", "-1", "NaN", "Infinity"])
def test_parse_price_invalid_rejected(value: str) -> None:
    with pytest.raises(NormalizationError):
        parse_price(value)


def test_resolve_currency_prefers_item_then_default() -> None:
    assert resolve_currency("eur", None) == "EUR"
    assert resolve_currency(None, "usd") == "USD"
    assert resolve_currency("GBP", "USD") == "GBP"


@pytest.mark.parametrize(
    ("item", "default"), [(None, None), (None, ""), ("US", None), ("US$", None)]
)
def test_resolve_currency_rejects_missing_or_invalid(item: str | None, default: str | None) -> None:
    with pytest.raises(NormalizationError):
        resolve_currency(item, default)


# --- normalize() mapping ------------------------------------------------------


def test_normalize_maps_all_fields() -> None:
    raw = _raw(external_id="7001", brand="Acme", image_url="https://cdn/x.jpg", in_stock=True)
    item = _normalize(raw)

    assert isinstance(item.product, Product)
    assert isinstance(item.observation, PriceObservation)
    assert item.product.id == "demo_rest:7001"
    assert item.product.source_id == "demo_rest"
    assert item.product.external_id == "7001"
    assert item.product.latest_price is not None
    assert item.product.latest_price.amount == Decimal("19.99")
    assert item.product.latest_price.currency == "USD"
    assert item.product.in_stock is True
    assert item.product.first_seen_at == _AT
    assert item.product.last_seen_at == _AT

    assert item.observation.product_id == "demo_rest:7001"
    assert item.observation.run_id == "run-1"
    assert item.observation.amount == Decimal("19.99")
    assert item.observation.currency == "USD"
    assert item.observation.captured_at == _AT


def test_normalize_applies_source_default_currency() -> None:
    raw = _raw(currency=None)  # source stated no currency (products.json)
    item = _normalize(raw, default_currency="USD")
    assert item.observation.currency == "USD"


def test_normalize_rejects_when_no_currency_available() -> None:
    raw = _raw(currency=None)
    with pytest.raises(NormalizationError):
        _normalize(raw, default_currency=None)


def test_normalize_collapses_title_whitespace() -> None:
    raw = _raw(title="  Trail   Runner\t2000 ")
    assert _normalize(raw).product.title == "Trail Runner 2000"


def test_normalize_rejects_whitespace_only_title() -> None:
    raw = _raw(title="   ")  # passes RawProduct min_length but empty once stripped
    with pytest.raises(NormalizationError):
        _normalize(raw)


def test_normalize_rejects_bad_price() -> None:
    raw = _raw(raw_price="call for price")
    with pytest.raises(NormalizationError):
        _normalize(raw)


def test_normalize_of_demo_rest_fixture() -> None:
    # The extractor's expected output normalizes cleanly with the source default currency.
    expected = json.loads((_FIXTURES / "expected_products.json").read_text())
    for entry in expected:
        raw = RawProduct(**entry)
        item = _normalize(raw, default_currency="USD")
        assert item.product.id == f"demo_rest:{entry['external_id']}"
        assert item.observation.currency == "USD"
        assert item.observation.amount == Decimal(entry["raw_price"])


# --- NormalizePipeline (Scrapy adapter) --------------------------------------


class _FakeSpider:
    name = "demo_rest"
    id = "demo_rest"
    run_id = "run-xyz"
    default_currency = "USD"


def _run_pipeline(items: list[object]) -> tuple[NormalizePipeline, list[NormalizedItem]]:
    pipe = NormalizePipeline()
    spider = _FakeSpider()
    pipe.open_spider(spider)  # type: ignore[arg-type]
    out: list[NormalizedItem] = []
    for item in items:
        with contextlib.suppress(DropItem):
            out.append(pipe.process_item(item, spider))  # type: ignore[arg-type]
    pipe.close_spider(spider)  # type: ignore[arg-type]
    return pipe, out


def test_pipeline_normalizes_valid_items() -> None:
    pipe, out = _run_pipeline([_raw(external_id="1"), _raw(external_id="2")])
    assert pipe.items_ok == 2
    assert pipe.items_rejected == 0
    assert [i.product.id for i in out] == ["demo_rest:1", "demo_rest:2"]


def test_pipeline_rejects_non_raw_product() -> None:
    pipe, out = _run_pipeline([{"external_id": "1"}, "garbage"])
    assert out == []
    assert pipe.items_rejected == 2
    assert pipe.items_ok == 0


def test_pipeline_rejects_unmappable_and_counts_it() -> None:
    pipe, out = _run_pipeline([_raw(external_id="ok"), _raw(external_id="bad", raw_price="free")])
    assert pipe.items_ok == 1
    assert pipe.items_rejected == 1
    assert [i.product.id for i in out] == ["demo_rest:ok"]


def test_pipeline_dedups_within_run_keep_first() -> None:
    first = _raw(external_id="dup", title="First")
    second = _raw(external_id="dup", title="Second")
    pipe, out = _run_pipeline([first, second])
    assert pipe.items_ok == 1
    assert pipe.items_duplicate == 1
    assert len(out) == 1
    assert out[0].product.title == "First"  # keep-first


def test_pipeline_uses_source_default_currency_for_currencyless_items() -> None:
    pipe, out = _run_pipeline([_raw(external_id="1", currency=None)])
    assert pipe.items_ok == 1
    assert out[0].observation.currency == "USD"


def test_pipeline_stamps_utc_captured_at() -> None:
    _, out = _run_pipeline([_raw(external_id="1")])
    captured = out[0].observation.captured_at
    assert captured.utcoffset() == timedelta(0)


def test_pipeline_run_id_from_spider() -> None:
    _, out = _run_pipeline([_raw(external_id="1")])
    assert out[0].observation.run_id == "run-xyz"


def test_pipeline_generates_run_id_when_spider_lacks_one() -> None:
    class _NoRunId:
        name = "demo_rest"
        id = "demo_rest"
        default_currency = "USD"

    pipe = NormalizePipeline()
    pipe.open_spider(_NoRunId())  # type: ignore[arg-type]
    assert pipe.run_id  # a fallback id was generated
