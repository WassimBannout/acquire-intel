"""Self-tests for the adversarial mock harness (T3.1, ADR-0009, docs/06 §4).

Prove each scenario is **deterministic** and behaves as documented, so downstream resilience
tasks can rely on it. Uses the Flask test client — no socket, no DB.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from harness import HarnessConfig, Scenario, create_harness_app

if TYPE_CHECKING:
    from collections.abc import Iterator

    from flask.testing import FlaskClient

_CFG = HarnessConfig(rate_limited_burst=2, block_after=3, retry_after_seconds=1)


@pytest.fixture
def client() -> Iterator[FlaskClient]:
    app = create_harness_app(_CFG)
    app.testing = True
    with app.test_client() as c:
        yield c


def _products_json(data: bytes) -> list[dict[str, object]]:
    payload = json.loads(data)
    assert isinstance(payload, dict)
    products = payload["products"]
    assert isinstance(products, list)
    return products


# --- happy path ---------------------------------------------------------------


def test_happy_serves_parseable_products(client: FlaskClient) -> None:
    resp = client.get("/happy/products.json")
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    products = _products_json(resp.data)
    assert len(products) == 3
    # The shape the REST extractor parses (id + variants[].price).
    assert products[0]["id"] == 9001
    assert products[0]["variants"][0]["price"] == "49.90"  # type: ignore[index]


def test_happy_pagination_is_empty_past_the_end(client: FlaskClient) -> None:
    resp = client.get("/happy/products.json", query_string={"page": 2})
    assert resp.status_code == 200
    assert _products_json(resp.data) == []


# --- rate limited: burst of 429s (with Retry-After), then success -------------


def test_rate_limited_bursts_then_succeeds(client: FlaskClient) -> None:
    # Exactly `rate_limited_burst` throttled responses (each carrying Retry-After)…
    for _ in range(_CFG.rate_limited_burst):
        throttled = client.get("/rate_limited/products.json")
        assert throttled.status_code == 429
        assert throttled.headers["Retry-After"] == str(_CFG.retry_after_seconds)

    # …then the same identity succeeds.
    final = client.get("/rate_limited/products.json")
    assert final.status_code == 200
    assert len(_products_json(final.data)) == 3


# --- block after N per identity; a fresh identity resets the budget -----------


def test_block_after_n_blocks_then_fresh_identity_recovers(client: FlaskClient) -> None:
    ua_a = {"User-Agent": "identity-A"}
    for _ in range(_CFG.block_after):
        assert client.get("/block_after_n/products.json", headers=ua_a).status_code == 200
    # The next request from the same identity is blocked.
    assert client.get("/block_after_n/products.json", headers=ua_a).status_code == 403

    # A different identity starts with a fresh budget → succeeds immediately.
    ua_b = {"User-Agent": "identity-B"}
    assert client.get("/block_after_n/products.json", headers=ua_b).status_code == 200


def test_explicit_identity_header_overrides_user_agent(client: FlaskClient) -> None:
    same_ua = {"User-Agent": "shared-ua"}
    a = {**same_ua, "X-Harness-Identity": "alpha"}
    b = {**same_ua, "X-Harness-Identity": "beta"}
    for _ in range(_CFG.block_after):
        assert client.get("/block_after_n/products.json", headers=a).status_code == 200
    assert client.get("/block_after_n/products.json", headers=a).status_code == 403
    # Same User-Agent but a different explicit identity is a distinct budget.
    assert client.get("/block_after_n/products.json", headers=b).status_code == 200


# --- captcha / challenge ------------------------------------------------------


def test_captcha_returns_challenge_not_data(client: FlaskClient) -> None:
    resp = client.get("/captcha/products.json")
    assert resp.status_code == 200  # a soft signal: 200 but not product data
    assert resp.mimetype == "text/html"
    body = resp.data.decode()
    assert "Please verify you are human" in body
    assert "captcha" in body


# --- cookie wall --------------------------------------------------------------


def test_cookie_wall_blocks_then_passes_once_cookie_carried(client: FlaskClient) -> None:
    first = client.get("/cookie_wall/products.json")
    assert first.status_code == 403
    set_cookie = first.headers.get("Set-Cookie", "")
    assert _CFG.session_cookie in set_cookie

    # The Flask test client persists cookies across requests → the retry carries it → success.
    second = client.get("/cookie_wall/products.json")
    assert second.status_code == 200
    assert len(_products_json(second.data)) == 3


# --- soft ban -----------------------------------------------------------------


def test_soft_ban_is_200_with_empty_body(client: FlaskClient) -> None:
    resp = client.get("/soft_ban/products.json")
    assert resp.status_code == 200
    assert resp.data == b""


# --- drift --------------------------------------------------------------------


def test_drift_keeps_envelope_but_renames_item_fields(client: FlaskClient) -> None:
    resp = client.get("/drift/products.json")
    assert resp.status_code == 200
    products = _products_json(resp.data)
    assert products, "drift still returns items, just mis-shaped"
    # None of the fields the extractor maps are present → every item is unmappable.
    for item in products:
        assert "id" not in item
        assert "variants" not in item


# --- control + errors ---------------------------------------------------------


def test_reset_clears_identity_counters(client: FlaskClient) -> None:
    ua = {"User-Agent": "resettable"}
    for _ in range(_CFG.block_after):
        assert client.get("/block_after_n/products.json", headers=ua).status_code == 200
    assert client.get("/block_after_n/products.json", headers=ua).status_code == 403

    assert client.post("/__admin__/reset").status_code == 204

    # After a reset the same identity's budget is fresh again → deterministic.
    assert client.get("/block_after_n/products.json", headers=ua).status_code == 200


def test_unknown_scenario_is_404(client: FlaskClient) -> None:
    resp = client.get("/definitely-not-a-scenario/products.json")
    assert resp.status_code == 404


def test_all_scenarios_are_routable(client: FlaskClient) -> None:
    # Every enum value is a live path (guards against the enum and server drifting apart).
    for scenario in Scenario:
        resp = client.get(f"/{scenario.value}/products.json")
        assert resp.status_code in {200, 403, 429}
