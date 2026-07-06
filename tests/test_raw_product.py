"""RawProduct model + SourceExtractor contract (T1.1, ADR-0003 / ADR-0008).

Two obligations:
- The pydantic ``RawProduct`` accepts valid input and rejects invalid input.
- It stays in **parity** with the published ``raw-product.schema.json`` contract (property
  set, required set, allowed JSON types, and closed-to-unknown-keys) so the runtime model and
  the language-agnostic contract can never silently diverge.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from acquire_intel.acquisition import RawProduct, SourceExtractor

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Any

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "specs" / "data-contracts" / "raw-product.schema.json"
)


def _published_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text())


def _json_types(node: dict[str, Any]) -> set[str]:
    """Normalize a schema node's allowed JSON types into a comparable set.

    Handles ``type`` as a string or a list, and pydantic's ``anyOf`` expansion for unions.
    Treats ``integer`` as ``number`` — every JSON integer is a number, and pydantic emits
    ``integer`` for ``int`` where the published contract uses the broader ``number``.
    """
    types: set[str] = set()
    if "anyOf" in node:
        for sub in node["anyOf"]:
            types |= _json_types(sub)
    declared = node.get("type")
    if isinstance(declared, list):
        types |= set(declared)
    elif isinstance(declared, str):
        types.add(declared)
    return {"number" if t == "integer" else t for t in types}


# --- valid / invalid acceptance ----------------------------------------------


def test_accepts_full_valid_product() -> None:
    product = RawProduct(
        external_id="SKU-1",
        title="Widget",
        url="https://shop.example/p/1",
        raw_price="19.99",
        currency="USD",
        in_stock=True,
        brand="Acme",
        image_url="https://shop.example/img/1.jpg",
        extra={"color": "red"},
    )
    assert product.external_id == "SKU-1"
    assert product.raw_price == "19.99"
    assert product.extra == {"color": "red"}


def test_accepts_minimal_product_and_applies_defaults() -> None:
    product = RawProduct(external_id="1", title="T", url="https://x", raw_price=10)
    assert product.currency is None
    assert product.in_stock is None
    assert product.brand is None
    assert product.image_url is None
    assert product.extra == {}


@pytest.mark.parametrize("price", ["19.99", 20, 19.99])
def test_raw_price_accepts_string_and_number(price: str | int | float) -> None:
    product = RawProduct(external_id="1", title="T", url="https://x", raw_price=price)
    assert product.raw_price == price


def test_rejects_empty_title() -> None:
    with pytest.raises(ValidationError):
        RawProduct(external_id="1", title="", url="https://x", raw_price=1)


@pytest.mark.parametrize("missing", ["external_id", "title", "url", "raw_price"])
def test_rejects_missing_required_field(missing: str) -> None:
    kwargs: dict[str, Any] = {
        "external_id": "1",
        "title": "T",
        "url": "https://x",
        "raw_price": 1,
    }
    del kwargs[missing]
    with pytest.raises(ValidationError):
        RawProduct(**kwargs)


def test_rejects_unknown_field() -> None:
    # A junk/blocked payload carrying unexpected keys must not construct (ADR-0008).
    kwargs: dict[str, Any] = {
        "external_id": "1",
        "title": "T",
        "url": "https://x",
        "raw_price": 1,
        "sneaky": "block-page-marker",
    }
    with pytest.raises(ValidationError):
        RawProduct(**kwargs)


# --- parity with the published JSON Schema contract --------------------------


def test_property_set_matches_contract() -> None:
    generated = RawProduct.model_json_schema()
    published = _published_schema()
    assert set(generated["properties"]) == set(published["properties"])


def test_required_set_matches_contract() -> None:
    generated = RawProduct.model_json_schema()
    published = _published_schema()
    assert set(generated["required"]) == set(published["required"])


def test_model_is_closed_to_unknown_keys_like_contract() -> None:
    generated = RawProduct.model_json_schema()
    published = _published_schema()
    assert published["additionalProperties"] is False
    assert generated.get("additionalProperties") is False


def test_each_property_allows_the_same_json_types() -> None:
    generated = RawProduct.model_json_schema()
    published = _published_schema()
    for name, published_prop in published["properties"].items():
        generated_prop = generated["properties"][name]
        assert _json_types(generated_prop) == _json_types(published_prop), name


def test_title_min_length_preserved() -> None:
    generated = RawProduct.model_json_schema()
    assert generated["properties"]["title"].get("minLength") == 1


# --- SourceExtractor protocol conformance ------------------------------------


class _ConformingExtractor:
    id = "demo_rest"
    kind = "rest"
    stale_after = timedelta(hours=6)

    def start_requests(self) -> Iterable[object]:
        return []

    def parse(self, response: object) -> Iterable[object]:
        return []


class _MissingMembers:
    id = "broken"


def test_conforming_object_satisfies_source_extractor() -> None:
    assert isinstance(_ConformingExtractor(), SourceExtractor)


def test_object_missing_members_is_not_a_source_extractor() -> None:
    assert not isinstance(_MissingMembers(), SourceExtractor)
