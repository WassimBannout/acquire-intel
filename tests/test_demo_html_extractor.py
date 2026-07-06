"""Fixture tests for the demo_html Playwright/HTML extractor (T2.1, ADR-0002).

Contract under test (``specs/extractor-interface.md``, docs/04 §1):
- A rendered snapshot → the exact expected ``RawProduct``s (resilient selectors, correct map).
- A per-card defect (missing price) → that card is skipped, not fabricated.
- A drifted snapshot (selectors moved) → **nothing** is emitted (rejection, not garbage).
- The listing request is Playwright-marked and waits for the product grid.
- A real browser render of a client-rendered page still parses (marked ``playwright``).

The HTML→``RawProduct`` map is a pure function, so most of this runs without a browser; only
the render smoke test needs Chromium (skipped cleanly when the binary is absent).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import scrapy
from scrapy.http import HtmlResponse, Request

from acquire_intel.acquisition import SourceExtractor, get_spider, known_sources
from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.acquisition.sources.demo_html import (
    DEMO_HTML_BASE_URL,
    DemoHtmlExtractor,
    parse_products,
)

if TYPE_CHECKING:
    from typing import Any

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "demo_html"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


def _expected() -> Any:
    return json.loads(_fixture("expected_products.json"))


# --- protocol / identity / registry ------------------------------------------


def test_extractor_satisfies_source_extractor_protocol() -> None:
    assert isinstance(DemoHtmlExtractor(), SourceExtractor)


def test_extractor_identity() -> None:
    extractor = DemoHtmlExtractor()
    assert extractor.id == "demo_html"
    assert extractor.kind == "html"


def test_registered_in_source_registry() -> None:
    assert "demo_html" in known_sources()
    assert get_spider("demo_html") is DemoHtmlExtractor
    assert issubclass(DemoHtmlExtractor, scrapy.Spider)


# --- request construction: Playwright-marked + waits -------------------------


def test_start_request_is_playwright_and_waits_for_grid() -> None:
    extractor = DemoHtmlExtractor(base_url="https://demo-html.example.com")
    [request] = list(extractor.start_requests())
    assert request.url == "https://demo-html.example.com/collections/all"
    assert request.meta["playwright"] is True
    # A wait-for-selector page method hydrates the grid before parse.
    methods = request.meta["playwright_page_methods"]
    assert methods[0].method == "wait_for_selector"
    assert methods[0].args == ("[data-product-id]",)


# --- rendered snapshot → expected RawProducts --------------------------------


def test_rendered_snapshot_yields_expected_products() -> None:
    products = parse_products(_fixture("rendered.html"), base_url=DEMO_HTML_BASE_URL)
    got = [p.model_dump(mode="json") for p in products]
    assert got == _expected()


def test_card_missing_price_is_skipped_not_fabricated() -> None:
    products = parse_products(_fixture("rendered.html"), base_url=DEMO_HTML_BASE_URL)
    assert all(p.external_id != "H-1003" for p in products)  # the price-less "Ghost Item"
    assert len(products) == 2


def test_all_emitted_items_are_valid_raw_products() -> None:
    products = parse_products(_fixture("rendered.html"), base_url=DEMO_HTML_BASE_URL)
    assert products
    assert all(isinstance(p, RawProduct) for p in products)


def test_currency_and_stock_are_read_from_data_hooks() -> None:
    by_id = {
        p.external_id: p
        for p in parse_products(_fixture("rendered.html"), base_url=DEMO_HTML_BASE_URL)
    }
    assert by_id["H-1001"].currency == "EUR"
    assert by_id["H-1001"].in_stock is True
    assert by_id["H-1002"].in_stock is False


def test_parse_via_spider_response_matches_pure_parser() -> None:
    """The spider's ``parse`` delegates to the pure parser on the rendered body."""
    extractor = DemoHtmlExtractor()
    request = Request(extractor._listing_url())
    response = HtmlResponse(
        url=extractor._listing_url(),
        body=_fixture("rendered.html").encode(),
        encoding="utf-8",
        request=request,
    )
    products = list(extractor.parse(response))
    assert [p.external_id for p in products] == ["H-1001", "H-1002"]


# --- selector drift → nothing ------------------------------------------------


def test_drifted_snapshot_yields_nothing() -> None:
    products = parse_products(_fixture("drifted.html"), base_url=DEMO_HTML_BASE_URL)
    assert products == []


def test_empty_html_yields_nothing() -> None:
    assert parse_products("<html><body></body></html>", base_url=DEMO_HTML_BASE_URL) == []


# --- real Playwright render smoke test ---------------------------------------


@pytest.mark.playwright
def test_playwright_renders_client_side_page() -> None:
    """A genuinely JS-rendered page (empty until scripted) parses after a real render."""
    playwright_sync = pytest.importorskip("playwright.sync_api")
    page_url = (_FIXTURES / "js_page.html").as_uri()

    with playwright_sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # browser binary not installed → skip cleanly
            pytest.skip(f"Chromium not available: {exc}")
        try:
            page = browser.new_page()
            page.goto(page_url)
            page.wait_for_selector("[data-product-id]")
            rendered_html = page.content()
        finally:
            browser.close()

    products = parse_products(rendered_html, base_url=DEMO_HTML_BASE_URL)
    # The initial document had no product nodes; JS built them and Playwright rendered them.
    assert [p.external_id for p in products] == ["H-1001", "H-1002"]
    assert products[0].title == "Aurora Daypack"
