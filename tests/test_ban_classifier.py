"""Unit + harness tests for the ban/anti-bot classifier (T3.2, ADR-0005, docs/04 §2.5).

Two layers of proof:
1. ``classify`` on synthetic (status, body) pairs — one per label, incl. the tricky cases
   (empty JSON array is *not* a ban; CAPTCHA markers win over a 200/403 status).
2. ``classify`` against the **real adversarial harness** (T3.1): every scenario the harness
   serves lands on its expected label — the deterministic adversary proving the detector.
"""

from __future__ import annotations

import pytest

from acquire_intel.resilience.classifier import (
    Classification,
    ban_kind,
    classify,
    is_ban,
    recommended_action,
)
from harness import HarnessConfig, Scenario, create_harness_app

# --- pure classification ------------------------------------------------------


def test_ok_when_2xx_with_a_body() -> None:
    assert classify(status=200, body=b'{"products": [{"id": 1}]}') is Classification.OK


def test_empty_json_array_is_ok_not_a_ban() -> None:
    # A legitimate end-of-pagination page has a non-empty body → never a soft-ban.
    assert classify(status=200, body=b'{"products": []}') is Classification.OK


def test_soft_ban_when_2xx_body_is_empty() -> None:
    assert classify(status=200, body=b"") is Classification.EMPTY
    assert classify(status=200, body=b"   \n\t ") is Classification.EMPTY


def test_rate_limited_on_429() -> None:
    assert classify(status=429, body=b'{"error": "slow down"}') is Classification.RATE_LIMITED


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_blocked_on_other_non_2xx(status: int) -> None:
    assert classify(status=status, body=b"Forbidden") is Classification.BLOCKED


def test_captcha_markers_win_over_status() -> None:
    body = b"<html><body>Please verify you are human</body></html>"
    assert classify(status=200, body=body) is Classification.CAPTCHA
    assert classify(status=403, body=body) is Classification.CAPTCHA


def test_captcha_marker_matching_is_case_insensitive() -> None:
    assert classify(status=200, body=b"JUST A MOMENT...") is Classification.CAPTCHA


# --- label → ban metadata -----------------------------------------------------


def test_is_ban_only_for_non_ok() -> None:
    assert not is_ban(Classification.OK)
    assert all(is_ban(c) for c in Classification if c is not Classification.OK)


def test_kind_and_action_maps_cover_every_ban_label() -> None:
    for c in Classification:
        if c is Classification.OK:
            continue
        assert ban_kind(c) == c.value  # kind wire value matches the label
        assert recommended_action(c) in {"backoff", "rotate_identity", "rotate_proxy", "give_up"}


# --- against the real adversarial harness -------------------------------------

_EXPECTED = {
    Scenario.HAPPY: Classification.OK,
    Scenario.RATE_LIMITED: Classification.RATE_LIMITED,
    Scenario.BLOCK_AFTER_N: Classification.BLOCKED,
    Scenario.CAPTCHA: Classification.CAPTCHA,
    Scenario.COOKIE_WALL: Classification.BLOCKED,  # a 403 cookie wall reads as blocked
    Scenario.SOFT_BAN: Classification.EMPTY,
    Scenario.DRIFT: Classification.OK,  # a 200 with data; drift is a quality-gate concern (T3.5)
}


@pytest.mark.parametrize("scenario", list(Scenario), ids=lambda s: s.value)
def test_harness_scenarios_classify_as_expected(scenario: Scenario) -> None:
    # burst=1 / block_after=0 make the very first request already exhibit the adversarial state.
    app = create_harness_app(HarnessConfig(rate_limited_burst=1, block_after=0))
    app.testing = True
    with app.test_client() as client:
        resp = client.get(f"/{scenario.value}/products.json")

    assert classify(status=resp.status_code, body=resp.data) is _EXPECTED[scenario]
