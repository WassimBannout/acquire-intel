"""IdentityRotationMiddleware tests (T3.4, ADR-0011, docs/04 §2.1-2.2).

The recovery is proven against the **real harness**: ``block_after_n`` (an identity's budget is
burned, the next request is 403, a rotation to a fresh identity resets it → success) and
``cookie_wall`` (a same-identity retry replays the session cookie the server just set → success).
Unit tests cover the respectful default (contact UA until a block), the bounded retry, and that a
rate-limit never rotates. The middleware's decisions are driven synchronously against a Flask
test client (whose own cookie jar stands in for Scrapy's ``CookiesMiddleware``), so the whole path
is deterministic without a live engine — mirroring ``test_recovery_middleware``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from scrapy.http import Request, TextResponse

from acquire_intel.resilience.identity import IdentityPool
from acquire_intel.resilience.middleware import (
    STAT_COOKIE_RETRIES,
    STAT_IDENTITY_ROTATIONS,
    STAT_ROTATION_EXHAUSTED,
    IdentityRotationMiddleware,
)
from acquire_intel.resilience.proxy import ProxyPool
from harness import HarnessConfig, create_harness_app

_URL = "https://shop.example.com/products.json"


class _FakeStats:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def inc_value(self, key: str, count: int = 1, start: int = 0) -> None:
        self.counts[key] = self.counts.get(key, start) + count


def _spider() -> Any:
    return SimpleNamespace(name="demo_rest", ban_events=[])


def _mw(stats: _FakeStats, *, proxies: ProxyPool | None = None, max_attempts: int = 6) -> Any:
    return IdentityRotationMiddleware(
        IdentityPool(), proxies or ProxyPool(), max_attempts=max_attempts, stats=stats
    )


def _resp(
    status: int,
    *,
    body: bytes = b"x",
    request: Request,
    headers: dict[str, str] | None = None,
) -> TextResponse:
    return TextResponse(
        url=request.url,
        status=status,
        body=body,
        request=request,
        encoding="utf-8",
        headers=headers or {},
    )


def _ua(request: Request) -> str | None:
    raw = request.headers.get(b"User-Agent")
    return raw.decode() if raw else None


# --- defaults & unit behaviour ------------------------------------------------


def test_default_posture_keeps_the_contact_user_agent() -> None:
    # Before any block we do NOT stamp a browser identity — the honest contact UA stays (docs/08).
    mw = _mw(_FakeStats())
    request = Request(_URL)
    mw.process_request(request, _spider())
    assert _ua(request) is None  # nothing stamped → Scrapy's USER_AGENT (contact) is used


def test_ok_response_passes_through_and_credits_the_proxy() -> None:
    proxies = ProxyPool(urls=["http://p1"])
    mw = _mw(_FakeStats(), proxies=proxies)
    request = Request(_URL)
    mw.process_request(request, _spider())
    assert request.meta["proxy"] == "http://p1"  # a configured proxy is attached even by default

    resp = _resp(200, body=b'{"products": []}', request=request)
    assert mw.process_response(request, resp, _spider()) is resp
    assert proxies.health()[0].successes == 1


def test_rate_limit_never_rotates() -> None:
    # 429 is transient and owned by BackoffRetryMiddleware — rotation must ignore it.
    stats = _FakeStats()
    mw = _mw(stats)
    request = Request(_URL)
    resp = _resp(429, request=request)
    assert mw.process_response(request, resp, _spider()) is resp
    assert STAT_IDENTITY_ROTATIONS not in stats.counts


def test_rotation_is_bounded_then_falls_through_to_the_ban_gate() -> None:
    stats = _FakeStats()
    mw = _mw(stats, max_attempts=2)
    meta: dict[str, Any] = {}
    for _ in range(5):
        request = Request(_URL, meta=dict(meta))
        out = mw.process_response(request, _resp(403, request=request, body=b"blocked"), _spider())
        if isinstance(out, Request):
            meta = dict(out.meta)
            continue
        break
    # Exactly max_attempts rotations, then the response falls through (exhausted recorded).
    assert stats.counts[STAT_IDENTITY_ROTATIONS] == 2
    assert stats.counts[STAT_ROTATION_EXHAUSTED] == 1


# --- real-harness recovery ----------------------------------------------------


def test_rotation_recovers_the_real_harness_block_after_n() -> None:
    # block_after=3 → an identity gets 3 OK responses; its 4th request is 403. A fresh identity
    # resets that budget, so the post-rotation retry succeeds (the T3.4 acceptance criterion).
    app = create_harness_app(HarnessConfig(block_after=3))
    app.testing = True
    stats = _FakeStats()
    mw = _mw(stats)
    spider = _spider()

    def fetch(client: Any, meta: dict[str, Any]) -> tuple[Request, TextResponse]:
        request = Request(_URL, meta=dict(meta))
        mw.process_request(request, spider)
        headers = {"User-Agent": _ua(request)} if _ua(request) else {}
        r = client.get("/block_after_n/products.json", headers=headers)
        return request, _resp(r.status_code, body=r.data or b"", request=request)

    with app.test_client() as client:
        meta: dict[str, Any] = {}
        # Burn identity A's budget: three successful fetches pass straight through.
        for _ in range(3):
            request, resp = fetch(client, meta)
            assert resp.status == 200
            assert mw.process_response(request, resp, spider) is resp

        # The 4th request is blocked; rotation returns a retry rather than dropping it.
        request, resp = fetch(client, meta)
        assert resp.status == 403
        blocked_ua = _ua(request)  # None → we were still on the contact UA
        out = mw.process_response(request, resp, spider)
        assert isinstance(out, Request)

        # The retry now presents a coherent *browser* identity and the harness serves data again.
        meta = dict(out.meta)
        request, resp = fetch(client, meta)
        assert _ua(request) is not None and _ua(request) != blocked_ua  # bundle actually swapped
        assert resp.status == 200
        assert mw.process_response(request, resp, spider) is resp

    assert stats.counts[STAT_IDENTITY_ROTATIONS] == 1


def test_cookie_wall_recovers_by_replaying_the_session_cookie() -> None:
    # cookie_wall → 403 + Set-Cookie until the session cookie is carried back. A same-identity
    # retry lets the client's cookie jar (standing in for CookiesMiddleware) replay it → 200.
    app = create_harness_app()
    app.testing = True
    stats = _FakeStats()
    mw = _mw(stats)
    spider = _spider()

    with app.test_client() as client:
        request = Request(_URL)
        mw.process_request(request, spider)
        first_ua = _ua(request)
        r = client.get("/cookie_wall/products.json")
        assert r.status_code == 403
        set_cookie = r.headers.get("Set-Cookie")
        assert set_cookie  # the server handed us a session cookie to replay
        resp = _resp(403, body=r.data or b"", request=request, headers={"Set-Cookie": set_cookie})
        out = mw.process_response(request, resp, spider)
        assert isinstance(out, Request)  # cookie retry, not a drop

        # Same identity (no rotation): the client jar replays the cookie → the wall opens.
        request2 = Request(_URL, meta=dict(out.meta))
        mw.process_request(request2, spider)
        assert _ua(request2) == first_ua  # identity unchanged
        r2 = client.get("/cookie_wall/products.json")
        assert r2.status_code == 200
        resp2 = _resp(200, body=r2.data or b"", request=request2)
        assert mw.process_response(request2, resp2, spider) is resp2

    assert stats.counts[STAT_COOKIE_RETRIES] == 1
    assert STAT_IDENTITY_ROTATIONS not in stats.counts  # a cookie wall must not rotate identity
