"""Adversarial scenarios served by the mock harness (T3.1, ADR-0009, docs/04 §4, docs/06 §4).

Each :class:`Scenario` maps to one adversarial behaviour the resilience layer must survive. The
behaviours are **deterministic** — given the same identity and request count, the harness always
responds the same way — so the collector can be driven into an exact failure mode and its recovery
asserted (no live hostile site, no flakiness).

This module is pure data + response construction: it holds the happy-path product catalogue (in
the Shopify-style ``products.json`` shape the REST extractor parses, docs/04 §1) and, for a given
scenario + per-identity request count, decides the HTTP status / headers / body. The Flask wiring
and per-identity counting live in :mod:`harness.server`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Scenario(StrEnum):
    """The selectable adversarial behaviours (the path segment that selects one)."""

    HAPPY = "happy"  # 200 + parseable product data
    RATE_LIMITED = "rate_limited"  # 429 + Retry-After for a burst, then success
    BLOCK_AFTER_N = "block_after_n"  # 403 once an identity exceeds a request budget
    CAPTCHA = "captcha"  # 200 with a JS/CAPTCHA challenge page (not data)
    COOKIE_WALL = "cookie_wall"  # 403 until the session cookie is carried back
    SOFT_BAN = "soft_ban"  # 200 with an empty body (a silent block)
    DRIFT = "drift"  # 200 with product-shaped data whose fields were renamed


@dataclass(frozen=True)
class HarnessConfig:
    """Deterministic thresholds for the count-based scenarios (overridable in tests)."""

    rate_limited_burst: int = 2  # number of 429s an identity gets before success
    retry_after_seconds: int = 1  # value of the Retry-After header on a 429
    block_after: int = 3  # requests an identity may make before BLOCK_AFTER_N returns 403
    page_size: int = 250  # happy-path pagination size (Shopify caps at 250)
    session_cookie: str = "harness_session"  # cookie COOKIE_WALL demands
    session_cookie_value: str = "let-me-in"  # value it sets / expects


# Happy-path catalogue in the exact shape ``DemoRestExtractor`` parses (docs/04 §1): a product is
# ``{id, title, handle, vendor, variants:[{price, available}], images:[{src}]}``. Small + fixed so
# tests and the T3.6 integration are deterministic.
CATALOG: list[dict[str, Any]] = [
    {
        "id": 9001,
        "title": "Harness Hoodie",
        "handle": "harness-hoodie",
        "vendor": "MockCo",
        "variants": [{"price": "49.90", "available": True}],
        "images": [{"src": "https://cdn.example.com/img/hoodie.jpg"}],
    },
    {
        "id": 9002,
        "title": "Adversary Mug",
        "handle": "adversary-mug",
        "vendor": "MockCo",
        "variants": [{"price": "12.50", "available": True}],
        "images": [{"src": "https://cdn.example.com/img/mug.jpg"}],
    },
    {
        "id": 9003,
        "title": "Backoff Beanie",
        "handle": "backoff-beanie",
        "vendor": "MockCo",
        "variants": [{"price": "19.00", "available": False}],
        "images": [],
    },
]

# A CAPTCHA / JS-challenge interstitial: HTTP 200 but plainly not product data. The classifier
# (T3.2) must catch it by body markers, not status alone.
CHALLENGE_HTML = """<!doctype html>
<html lang="en">
  <head><title>Just a moment...</title></head>
  <body>
    <div id="challenge-form" class="captcha">
      <h1>Please verify you are human</h1>
      <p>Enable JavaScript and complete the CAPTCHA to continue.</p>
      <noscript>This site requires JavaScript and cookies.</noscript>
    </div>
  </body>
</html>
"""

# A minimal cookie-wall interstitial returned until the session cookie is presented.
COOKIE_WALL_HTML = """<!doctype html>
<html lang="en">
  <head><title>Verifying your browser</title></head>
  <body><p>Setting a session cookie — please retry.</p></body>
</html>
"""


def happy_page(page: int, page_size: int) -> dict[str, Any]:
    """Return the ``{"products": [...]}`` envelope for 1-indexed ``page`` (empty past the end)."""
    start = max(page - 1, 0) * page_size
    return {"products": CATALOG[start : start + page_size]}


def drift_page(page: int, page_size: int) -> dict[str, Any]:
    """Return the happy envelope with **renamed item fields** (selector/shape drift).

    The envelope is intact (``{"products": [...]}``) but each item's keys are renamed, so an
    extractor mapping ``id``/``variants`` finds neither and skips every item — the drift the
    quality gate (T3.5) flags without crashing.
    """
    renamed = [
        {
            "product_id": p["id"],  # was "id"
            "name": p["title"],  # was "title"
            "slug": p["handle"],  # was "handle"
            "cost": p["variants"][0]["price"] if p["variants"] else None,  # was variants[].price
        }
        for p in CATALOG[max(page - 1, 0) * page_size : page * page_size]
    ]
    return {"products": renamed}
