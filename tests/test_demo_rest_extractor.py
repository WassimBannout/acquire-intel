"""Fixture tests for the demo_rest REST extractor (T1.3, ADR-0004).

Contract under test (``specs/extractor-interface.md``):
- A valid page → the exact expected ``RawProduct``s (per-item mapping correct).
- A per-item defect (missing price) → that item is skipped, not fabricated.
- A malformed / block payload → **nothing** is emitted (no junk cached as data).
- Pagination is driven by follow-up ``Request``s, and stops on an empty page.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import scrapy
from scrapy.http import Request, TextResponse

from acquire_intel.acquisition import SourceExtractor
from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.acquisition.sources.demo_rest import DemoRestExtractor

if TYPE_CHECKING:
    from typing import Any

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "demo_rest"


def _load(name: str) -> Any:
    return json.loads((_FIXTURES / name).read_text())


def _response_for(page: int, payload: Any, extractor: DemoRestExtractor) -> TextResponse:
    """Build a Scrapy response as the engine would deliver it to ``parse``."""
    body = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
    url = extractor._page_url(page)
    request = Request(url, meta={"page": page})
    return TextResponse(url=url, body=body, encoding="utf-8", request=request)


def _parse(extractor: DemoRestExtractor, response: TextResponse) -> list[Any]:
    return list(extractor.parse(response))


def _split(results: list[Any]) -> tuple[list[RawProduct], list[Request]]:
    products = [r for r in results if isinstance(r, RawProduct)]
    requests = [r for r in results if isinstance(r, Request)]
    return products, requests


# --- protocol conformance -----------------------------------------------------


def test_extractor_satisfies_source_extractor_protocol() -> None:
    assert isinstance(DemoRestExtractor(), SourceExtractor)


def test_extractor_identity() -> None:
    extractor = DemoRestExtractor()
    assert extractor.id == "demo_rest"
    assert extractor.kind == "rest"


def test_start_requests_targets_first_page() -> None:
    extractor = DemoRestExtractor(base_url="https://shop.example.com")
    requests = list(extractor.start_requests())
    assert len(requests) == 1
    assert requests[0].url == "https://shop.example.com/products.json?limit=250&page=1"
    assert requests[0].meta["page"] == 1


# --- valid payload → correct RawProducts -------------------------------------


def test_valid_payload_yields_expected_products() -> None:
    extractor = DemoRestExtractor(base_url="https://shop.example.com")
    response = _response_for(1, _load("valid_payload.json"), extractor)

    products, _ = _split(_parse(extractor, response))
    got = [p.model_dump(mode="json") for p in products]

    assert got == _load("expected_products.json")


def test_item_missing_price_is_skipped_not_fabricated() -> None:
    # The fixture's third product has no variants/price; it must not appear.
    extractor = DemoRestExtractor()
    response = _response_for(1, _load("valid_payload.json"), extractor)

    products, _ = _split(_parse(extractor, response))
    assert all(p.title != "Broken Product (no price)" for p in products)
    assert len(products) == 2


def test_all_emitted_items_are_valid_raw_products() -> None:
    extractor = DemoRestExtractor()
    response = _response_for(1, _load("valid_payload.json"), extractor)
    products, _ = _split(_parse(extractor, response))
    assert products  # non-empty
    assert all(isinstance(p, RawProduct) for p in products)


# --- pagination ---------------------------------------------------------------


def test_non_empty_page_follows_to_next_page() -> None:
    extractor = DemoRestExtractor(base_url="https://shop.example.com")
    response = _response_for(1, _load("valid_payload.json"), extractor)

    _, requests = _split(_parse(extractor, response))
    assert len(requests) == 1
    assert requests[0].url == "https://shop.example.com/products.json?limit=250&page=2"
    assert requests[0].meta["page"] == 2


def test_empty_page_stops_pagination() -> None:
    extractor = DemoRestExtractor()
    response = _response_for(2, {"products": []}, extractor)

    products, requests = _split(_parse(extractor, response))
    assert products == []
    assert requests == []  # no further pages


# --- malformed / blocked payloads → nothing ----------------------------------


def test_malformed_payload_yields_nothing() -> None:
    extractor = DemoRestExtractor()
    response = _response_for(1, _load("malformed_payload.json"), extractor)

    results = _parse(extractor, response)
    assert results == []  # no products AND no follow-up page


def test_non_json_block_page_yields_nothing() -> None:
    extractor = DemoRestExtractor()
    url = extractor._page_url(1)
    request = Request(url, meta={"page": 1})
    response = TextResponse(
        url=url,
        body=b"<html><body>Are you a robot? Please verify.</body></html>",
        encoding="utf-8",
        request=request,
    )
    assert _parse(extractor, response) == []


def test_wrong_shape_json_yields_nothing() -> None:
    extractor = DemoRestExtractor()
    response = _response_for(1, {"data": {"items": []}}, extractor)
    assert _parse(extractor, response) == []


# --- registry wiring ----------------------------------------------------------


def test_registered_in_source_registry() -> None:
    from acquire_intel.acquisition import get_spider, known_sources

    assert "demo_rest" in known_sources()
    assert get_spider("demo_rest") is DemoRestExtractor
    assert issubclass(DemoRestExtractor, scrapy.Spider)
