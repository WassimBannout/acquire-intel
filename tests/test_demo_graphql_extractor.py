"""Fixture tests for the demo_graphql GraphQL extractor (T2.2, ADR-0004).

Contract under test (``specs/extractor-interface.md``):
- A valid GraphQL page → the exact expected ``RawProduct``s (per-node mapping correct).
- A per-node defect (missing price) → that node is skipped, not fabricated.
- A malformed response (GraphQL ``errors`` / block / wrong shape) → **nothing** is emitted.
- Pagination is driven by follow-up POST ``Request``s carrying the ``after`` cursor, and stops
  when ``pageInfo.hasNextPage`` is false.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import scrapy
from scrapy.http import JsonRequest, Request, TextResponse

from acquire_intel.acquisition import SourceExtractor
from acquire_intel.acquisition.extractor import RawProduct
from acquire_intel.acquisition.sources.demo_graphql import DemoGraphqlExtractor

if TYPE_CHECKING:
    from typing import Any

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "demo_graphql"


def _load(name: str) -> Any:
    return json.loads((_FIXTURES / name).read_text())


def _response_for(payload: Any, extractor: DemoGraphqlExtractor) -> TextResponse:
    """Build a Scrapy response as the engine would deliver it to ``parse``."""
    body = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
    request = extractor._graphql_request(after=None)
    return TextResponse(url=extractor._endpoint, body=body, encoding="utf-8", request=request)


def _parse(extractor: DemoGraphqlExtractor, response: TextResponse) -> list[Any]:
    return list(extractor.parse(response))


def _split(results: list[Any]) -> tuple[list[RawProduct], list[Request]]:
    products = [r for r in results if isinstance(r, RawProduct)]
    requests = [r for r in results if isinstance(r, Request)]
    return products, requests


def _request_variables(request: Request) -> dict[str, Any]:
    """Decode the ``variables`` from a GraphQL POST body."""
    return json.loads(request.body)["variables"]  # type: ignore[no-any-return]


# --- protocol conformance -----------------------------------------------------


def test_extractor_satisfies_source_extractor_protocol() -> None:
    assert isinstance(DemoGraphqlExtractor(), SourceExtractor)


def test_extractor_identity() -> None:
    extractor = DemoGraphqlExtractor()
    assert extractor.id == "demo_graphql"
    assert extractor.kind == "graphql"


def test_start_request_is_a_typed_graphql_post() -> None:
    extractor = DemoGraphqlExtractor(base_url="https://graphql.example.com", page_size=25)
    requests = list(extractor.start_requests())
    assert len(requests) == 1
    request = requests[0]

    assert isinstance(request, JsonRequest)
    assert request.method == "POST"
    assert request.url == "https://graphql.example.com/api/2024-01/graphql.json"
    assert request.headers.get(b"Content-Type") == b"application/json"

    body = json.loads(request.body)
    assert "query Products($first: Int!, $after: String)" in body["query"]
    assert body["variables"] == {"first": 25, "after": None}


# --- valid payload → correct RawProducts -------------------------------------


def test_valid_payload_yields_expected_products() -> None:
    extractor = DemoGraphqlExtractor(base_url="https://graphql.example.com")
    response = _response_for(_load("response_page1.json"), extractor)

    products, _ = _split(_parse(extractor, response))
    got = [p.model_dump(mode="json") for p in products]

    assert got == _load("expected_products.json")


def test_node_missing_price_is_skipped_not_fabricated() -> None:
    # The fixture's third node has a null minVariantPrice; it must not appear.
    extractor = DemoGraphqlExtractor()
    response = _response_for(_load("response_page1.json"), extractor)

    products, _ = _split(_parse(extractor, response))
    assert all(p.title != "Ghost Product (no price)" for p in products)
    assert len(products) == 2


def test_per_node_currency_is_carried_through() -> None:
    extractor = DemoGraphqlExtractor()
    response = _response_for(_load("response_page1.json"), extractor)
    products, _ = _split(_parse(extractor, response))
    assert {p.currency for p in products} == {"EUR"}


# --- cursor pagination --------------------------------------------------------


def test_has_next_page_follows_cursor() -> None:
    extractor = DemoGraphqlExtractor()
    response = _response_for(_load("response_page1.json"), extractor)

    _, requests = _split(_parse(extractor, response))
    assert len(requests) == 1
    assert isinstance(requests[0], JsonRequest)
    assert _request_variables(requests[0])["after"] == "eyJsYXN0X2lkIjo4MDAzfQ=="


def test_last_page_stops_pagination() -> None:
    extractor = DemoGraphqlExtractor()
    response = _response_for(_load("response_page2.json"), extractor)

    products, requests = _split(_parse(extractor, response))
    assert len(products) == 1  # the final page still yields its node
    assert requests == []  # hasNextPage=false → no follow-up


# --- malformed / blocked responses → nothing ---------------------------------


def test_graphql_errors_payload_yields_nothing() -> None:
    extractor = DemoGraphqlExtractor()
    response = _response_for(_load("malformed_response.json"), extractor)
    assert _parse(extractor, response) == []  # no products AND no follow-up page


def test_non_json_block_page_yields_nothing() -> None:
    extractor = DemoGraphqlExtractor()
    request = extractor._graphql_request(after=None)
    response = TextResponse(
        url=extractor._endpoint,
        body=b"<html><body>Are you a robot? Please verify.</body></html>",
        encoding="utf-8",
        request=request,
    )
    assert _parse(extractor, response) == []


def test_wrong_shape_json_yields_nothing() -> None:
    extractor = DemoGraphqlExtractor()
    response = _response_for({"data": {"collections": {"edges": []}}}, extractor)
    assert _parse(extractor, response) == []


def test_empty_connection_yields_nothing_and_stops() -> None:
    extractor = DemoGraphqlExtractor()
    payload = {"data": {"products": {"edges": [], "pageInfo": {"hasNextPage": False}}}}
    response = _response_for(payload, extractor)
    assert _parse(extractor, response) == []


# --- registry wiring ----------------------------------------------------------


def test_registered_in_source_registry() -> None:
    from acquire_intel.acquisition import get_spider, known_sources

    assert "demo_graphql" in known_sources()
    assert get_spider("demo_graphql") is DemoGraphqlExtractor
    assert issubclass(DemoGraphqlExtractor, scrapy.Spider)
