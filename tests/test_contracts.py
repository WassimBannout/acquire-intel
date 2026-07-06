"""Canonical contract models: JSON Schema parity + money/UTC invariants (T1.2).

Two obligations (ADR-0008, docs/03):
- Each pydantic model stays in **parity** with its published JSON Schema in
  ``specs/data-contracts/`` (property set, required set, closed-to-unknown-keys, serialized
  types, date-time formats) so the runtime model and the language-agnostic contract can never
  silently diverge.
- The core invariants hold: money is ``Decimal`` + currency (serialized as a string, never a
  float) and every timestamp is timezone-aware and normalized to UTC.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from acquire_intel.contracts import (
    BanEvent,
    CrawlRun,
    Money,
    PriceObservation,
    Product,
)

if TYPE_CHECKING:
    from typing import Any

    from pydantic import BaseModel

_CONTRACTS = Path(__file__).resolve().parents[1] / "specs" / "data-contracts"
_AWARE = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _load(name: str) -> dict[str, Any]:
    return json.loads((_CONTRACTS / name).read_text())


def _json_types(node: dict[str, Any]) -> set[str]:
    """Allowed JSON types for a schema node, normalized for comparison.

    Handles ``type`` (str or list), ``anyOf``/``oneOf`` expansion, and ``$ref`` (a referenced
    object). Treats ``integer`` as ``number`` — every integer is a number, and pydantic emits
    ``integer`` for ``int`` where the contracts use the broader ``number``.
    """
    types: set[str] = set()
    if "$ref" in node:
        types.add("object")
    for combinator in ("anyOf", "oneOf"):
        for sub in node.get(combinator, []):
            types |= _json_types(sub)
    declared = node.get("type")
    if isinstance(declared, list):
        types |= set(declared)
    elif isinstance(declared, str):
        types.add(declared)
    return {"number" if t == "integer" else t for t in types}


def _formats(node: dict[str, Any]) -> set[str]:
    """Every ``format`` reachable in a node (recursing through anyOf/oneOf)."""
    formats: set[str] = set()
    fmt = node.get("format")
    if isinstance(fmt, str):
        formats.add(fmt)
    for combinator in ("anyOf", "oneOf"):
        for sub in node.get(combinator, []):
            formats |= _formats(sub)
    return formats


def assert_model_matches_schema(model: type[BaseModel], schema: dict[str, Any]) -> None:
    """Assert a pydantic model is in parity with a published JSON Schema.

    Property set, required set, and closed-ness come from the *validation* schema (fields with
    defaults are optional). Per-property types + formats come from the *serialization* schema
    so ``Decimal`` -> string and ``datetime`` -> date-time match the contract's on-the-wire
    shape rather than the looser input shape.
    """
    validation = model.model_json_schema()
    serialization = model.model_json_schema(mode="serialization")

    assert set(validation["properties"]) == set(schema["properties"]), "property set"
    assert set(validation.get("required", [])) == set(schema.get("required", [])), "required"
    assert validation.get("additionalProperties") is False
    assert schema.get("additionalProperties") is False

    for name, want in schema["properties"].items():
        got = serialization["properties"][name]
        assert _json_types(got) == _json_types(want), f"types: {name}"
        assert _formats(got) == _formats(want), f"format: {name}"


# --- parity vs the published contracts ---------------------------------------


def test_money_parity() -> None:
    assert_model_matches_schema(Money, _load("product.schema.json")["$defs"]["Money"])


def test_product_parity() -> None:
    assert_model_matches_schema(Product, _load("product.schema.json"))


def test_price_observation_parity() -> None:
    assert_model_matches_schema(PriceObservation, _load("price-observation.schema.json"))


def test_crawl_run_parity() -> None:
    assert_model_matches_schema(CrawlRun, _load("crawl-run.schema.json"))


def test_ban_event_parity() -> None:
    assert_model_matches_schema(BanEvent, _load("crawl-run.schema.json")["$defs"]["BanEvent"])


# --- money is Decimal + currency, never a float ------------------------------


def test_money_amount_is_decimal() -> None:
    money = Money(amount="19.99", currency="USD")
    assert isinstance(money.amount, Decimal)
    assert money.amount == Decimal("19.99")


def test_money_serializes_amount_as_string_not_float() -> None:
    dumped = Money(amount=Decimal("19.99"), currency="USD").model_dump(mode="json")
    assert dumped == {"amount": "19.99", "currency": "USD"}
    assert isinstance(dumped["amount"], str)


def test_money_requires_currency() -> None:
    kwargs: dict[str, Any] = {"amount": "1"}
    with pytest.raises(ValidationError):
        Money(**kwargs)


def test_money_rejects_unknown_field() -> None:
    kwargs: dict[str, Any] = {"amount": "1", "currency": "USD", "symbol": "$"}
    with pytest.raises(ValidationError):
        Money(**kwargs)


def test_price_observation_amount_is_decimal() -> None:
    obs = PriceObservation(
        product_id="s:1",
        source_id="s",
        run_id="r",
        amount="12.50",
        currency="USD",
        captured_at=_AWARE,
    )
    assert isinstance(obs.amount, Decimal)
    assert obs.amount == Decimal("12.50")


# --- timestamps are timezone-aware and normalized to UTC ---------------------


def test_naive_datetime_is_rejected() -> None:
    kwargs: dict[str, Any] = {
        "product_id": "s:1",
        "source_id": "s",
        "run_id": "r",
        "amount": Decimal("1"),
        "currency": "USD",
        "captured_at": datetime(2026, 1, 1, 12, 0, 0),  # naive: no tzinfo
    }
    with pytest.raises(ValidationError):
        PriceObservation(**kwargs)


def test_aware_datetime_normalized_to_utc() -> None:
    plus_two = timezone(timedelta(hours=2))
    obs = PriceObservation(
        product_id="s:1",
        source_id="s",
        run_id="r",
        amount=Decimal("1"),
        currency="USD",
        captured_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=plus_two),
    )
    assert obs.captured_at.utcoffset() == timedelta(0)
    assert obs.captured_at == datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


# --- Product ------------------------------------------------------------------


def test_product_accepts_money_and_defaults_optionals() -> None:
    product = Product(
        id="s:1",
        source_id="s",
        external_id="1",
        title="T",
        url="https://x",
        latest_price=Money(amount=Decimal("9.99"), currency="USD"),
        first_seen_at=_AWARE,
        last_seen_at=_AWARE,
    )
    assert product.latest_price is not None
    assert product.latest_price.amount == Decimal("9.99")
    assert product.brand is None
    assert product.in_stock is None


def test_product_latest_price_is_optional() -> None:
    product = Product(
        id="s:1",
        source_id="s",
        external_id="1",
        title="T",
        url="https://x",
        first_seen_at=_AWARE,
        last_seen_at=_AWARE,
    )
    assert product.latest_price is None


def test_product_rejects_empty_title() -> None:
    kwargs: dict[str, Any] = {
        "id": "s:1",
        "source_id": "s",
        "external_id": "1",
        "title": "",
        "url": "https://x",
        "first_seen_at": _AWARE,
        "last_seen_at": _AWARE,
    }
    with pytest.raises(ValidationError):
        Product(**kwargs)


# --- CrawlRun / BanEvent ------------------------------------------------------


def test_crawl_run_applies_defaults() -> None:
    run = CrawlRun(id="r1", source_id="s", status="running", started_at=_AWARE)
    assert run.items_ok == 0
    assert run.items_rejected == 0
    assert run.ban_events == []
    assert run.timings == {}
    assert run.finished_at is None


def test_crawl_run_rejects_unknown_status() -> None:
    kwargs: dict[str, Any] = {
        "id": "r1",
        "source_id": "s",
        "status": "explode",
        "started_at": _AWARE,
    }
    with pytest.raises(ValidationError):
        CrawlRun(**kwargs)


def test_crawl_run_rejects_negative_counts() -> None:
    kwargs: dict[str, Any] = {
        "id": "r1",
        "source_id": "s",
        "status": "running",
        "started_at": _AWARE,
        "items_ok": -1,
    }
    with pytest.raises(ValidationError):
        CrawlRun(**kwargs)


def test_crawl_run_holds_ban_events() -> None:
    run = CrawlRun(
        id="r1",
        source_id="s",
        status="partial",
        started_at=_AWARE,
        ban_events=[BanEvent(kind="blocked", action_taken="rotate_identity", occurred_at=_AWARE)],
    )
    assert run.ban_events[0].kind == "blocked"
    assert run.ban_events[0].action_taken == "rotate_identity"


@pytest.mark.parametrize("kind", ["rate_limited", "blocked", "captcha", "empty"])
def test_ban_event_kinds_accepted(kind: str) -> None:
    kwargs: dict[str, Any] = {"kind": kind, "action_taken": "backoff", "occurred_at": _AWARE}
    event = BanEvent(**kwargs)
    assert event.kind == kind


def test_ban_event_rejects_unknown_action() -> None:
    kwargs: dict[str, Any] = {
        "kind": "blocked",
        "action_taken": "panic",
        "occurred_at": _AWARE,
    }
    with pytest.raises(ValidationError):
        BanEvent(**kwargs)
