"""The adversarial mock server (T3.1, ADR-0009, docs/04 §4, docs/06 §4).

A small, fully-controlled Flask app the resilience layer is tested against. Scenarios are selected
by URL path — ``GET /<scenario>/products.json`` — and the count-based ones (rate-limit, block) key
their state on the caller's **identity** so that rotating identity (a fresh User-Agent, as the
identity layer will do in T3.4) resets the budget, exactly as a real anti-bot system behaves.

Determinism (ADR-0009): state is in-memory and reset via ``POST /__admin__/reset``, so a test can
put the server into a known state and assert an exact response sequence. Nothing here talks to the
network, a database, or the app package — it is a self-contained adversary.

Run it:  ``uv run python -m harness.server``  (see ``harness/README.md``).
"""

from __future__ import annotations

import argparse
import json
import threading
from typing import TYPE_CHECKING

from flask import Flask, Request, Response, request

from harness.scenarios import (
    CHALLENGE_HTML,
    COOKIE_WALL_HTML,
    HarnessConfig,
    Scenario,
    drift_page,
    happy_page,
)

if TYPE_CHECKING:
    from flask.typing import ResponseReturnValue

_IDENTITY_HEADER = "X-Harness-Identity"


class _IdentityCounter:
    """Thread-safe per-``(scenario, identity)`` request counter for the count-based scenarios."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def bump(self, scenario: str, identity: str) -> int:
        """Increment and return the count of prior requests (0 on the first) for this pair."""
        key = (scenario, identity)
        with self._lock:
            prior = self._counts.get(key, 0)
            self._counts[key] = prior + 1
            return prior

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


def _identity(req: Request) -> str:
    """Resolve the caller's identity: explicit header → User-Agent → remote address.

    The real collector rotates its User-Agent as part of a coherent identity bundle (T3.4), so
    keying on it means a rotation naturally presents as a new identity here.
    """
    return (
        req.headers.get(_IDENTITY_HEADER)
        or req.headers.get("User-Agent")
        or (req.remote_addr or "anonymous")
    )


def create_harness_app(config: HarnessConfig | None = None) -> Flask:
    """Build the harness Flask app (an app factory, so tests get isolated instances)."""
    cfg = config or HarnessConfig()
    app = Flask(__name__)
    counter = _IdentityCounter()

    @app.get("/")
    def index() -> ResponseReturnValue:
        scenarios = "\n".join(f"  GET /{s.value}/products.json" for s in Scenario)
        return Response(f"AcquireIntel adversarial harness\n\n{scenarios}\n", mimetype="text/plain")

    @app.post("/__admin__/reset")
    def reset() -> ResponseReturnValue:
        """Clear all per-identity counters so a test starts from a known state."""
        counter.reset()
        return "", 204

    @app.get("/<scenario>/products.json")
    def products(scenario: str) -> ResponseReturnValue:
        try:
            selected = Scenario(scenario)
        except ValueError:
            return Response(f"unknown scenario: {scenario}\n", status=404, mimetype="text/plain")

        page = request.args.get("page", default=1, type=int)
        count = counter.bump(selected.value, _identity(request))
        return _respond(selected, count=count, page=page, cfg=cfg)

    return app


def _respond(scenario: Scenario, *, count: int, page: int, cfg: HarnessConfig) -> Response:
    """Build the deterministic response for one request under ``scenario``."""
    if scenario is Scenario.HAPPY:
        return _json(happy_page(page, cfg.page_size))

    if scenario is Scenario.RATE_LIMITED:
        # A burst of 429s (honouring Retry-After) for this identity, then it succeeds.
        if count < cfg.rate_limited_burst:
            resp = _json({"error": "rate limited"}, status=429)
            resp.headers["Retry-After"] = str(cfg.retry_after_seconds)
            return resp
        return _json(happy_page(page, cfg.page_size))

    if scenario is Scenario.BLOCK_AFTER_N:
        # An identity may make `block_after` requests; the next is blocked. A fresh identity
        # resets the budget (its count restarts at 0) — the rotation path T3.4 exercises.
        if count < cfg.block_after:
            return _json(happy_page(page, cfg.page_size))
        return Response(
            "<html><body>403 Forbidden — access denied</body></html>",
            status=403,
            mimetype="text/html",
        )

    if scenario is Scenario.CAPTCHA:
        # HTTP 200 but a challenge page, never product data — must be caught by body markers.
        return Response(CHALLENGE_HTML, status=200, mimetype="text/html")

    if scenario is Scenario.COOKIE_WALL:
        if request.cookies.get(cfg.session_cookie) == cfg.session_cookie_value:
            return _json(happy_page(page, cfg.page_size))
        resp = Response(COOKIE_WALL_HTML, status=403, mimetype="text/html")
        resp.set_cookie(cfg.session_cookie, cfg.session_cookie_value)
        return resp

    if scenario is Scenario.SOFT_BAN:
        # A silent block: 200 OK with an empty body (looks fine by status, carries no data).
        return Response("", status=200, mimetype="application/json")

    # Scenario.DRIFT — 200 with product-shaped data whose item fields were renamed.
    return _json(drift_page(page, cfg.page_size))


def _json(payload: object, *, status: int = 200) -> Response:
    """A JSON response without importing app helpers (the harness stays self-contained)."""
    return Response(json.dumps(payload), status=status, mimetype="application/json")


def main() -> None:  # pragma: no cover - manual entrypoint
    parser = argparse.ArgumentParser(description="AcquireIntel adversarial mock harness")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--block-after",
        type=int,
        default=HarnessConfig.block_after,
        help="requests an identity may make before block_after_n returns 403 "
        "(use 1 to force an identity rotation within a single demo crawl)",
    )
    parser.add_argument(
        "--rate-limit-burst",
        type=int,
        default=HarnessConfig.rate_limited_burst,
        help="number of 429s an identity gets on rate_limited before a 200",
    )
    args = parser.parse_args()
    cfg = HarnessConfig(block_after=args.block_after, rate_limited_burst=args.rate_limit_burst)
    create_harness_app(cfg).run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":  # pragma: no cover
    main()
