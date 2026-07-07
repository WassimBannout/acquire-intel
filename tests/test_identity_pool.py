"""IdentityPool + BrowserProfile tests (T3.4, ADR-0011, docs/04 §2.2).

Proves the pool hands out a stable current identity, rotates round-robin with a fresh cookie-jar
key each generation, and — critically — that every catalogue bundle is *coherent* (a Chromium UA
carries ``sec-ch-ua`` client hints; a non-Chromium UA does not), since an incoherent bundle is
itself a bot signal.
"""

from __future__ import annotations

import pytest

from acquire_intel.resilience.identity import (
    BrowserProfile,
    Identity,
    IdentityPool,
)


def _profile(name: str, ua: str) -> BrowserProfile:
    return BrowserProfile(
        name=name, user_agent=ua, headers={}, viewport=(1920, 1080), locale="en-US"
    )


def test_current_is_stable_until_rotated() -> None:
    pool = IdentityPool()
    first = pool.current
    assert pool.current is first  # no rotation → same identity object returned


def test_rotate_advances_round_robin_with_fresh_generation() -> None:
    a = _profile("a", "UA-A")
    b = _profile("b", "UA-B")
    pool = IdentityPool(profiles=(a, b))

    assert pool.current.profile is a
    assert pool.current.key == "a#0"

    second = pool.rotate()
    assert second.profile is b
    assert second.key == "b#1"

    third = pool.rotate()  # wraps back to profile a, but a *new* generation
    assert third.profile is a
    assert third.key == "a#2"


def test_rotation_keys_are_unique_so_cookie_jars_never_collide() -> None:
    pool = IdentityPool()
    keys = [pool.current.key] + [pool.rotate().key for _ in range(12)]
    assert len(keys) == len(set(keys))  # every generation gets a distinct cookie-jar key


def test_default_catalogue_bundles_are_coherent() -> None:
    # Chromium UAs must carry sec-ch-ua client hints; Firefox/Safari UAs must not (docs/04 §2.2).
    pool = IdentityPool()
    seen = {pool.current.key: pool.current}
    while True:
        nxt = pool.rotate()
        if nxt.key in seen or nxt.profile.name in {i.profile.name for i in seen.values()}:
            break
        seen[nxt.key] = nxt

    for identity in seen.values():
        ua = identity.user_agent
        has_client_hints = any(h.lower() == "sec-ch-ua" for h in identity.headers)
        is_chromium = "Chrome/" in ua and "Firefox" not in ua
        assert has_client_hints == is_chromium, f"incoherent bundle: {identity.profile.name}"
        # Never advertise Accept/Accept-Encoding from the identity (owned by the request/Scrapy).
        lowered = {h.lower() for h in identity.headers}
        assert "accept" not in lowered
        assert "accept-encoding" not in lowered


def test_identity_exposes_profile_fields() -> None:
    p = BrowserProfile(
        name="x",
        user_agent="UA",
        headers={"Accept-Language": "en"},
        viewport=(800, 600),
        locale="fr",
    )
    ident = Identity(key="x#0", profile=p)
    assert ident.user_agent == "UA"
    assert ident.headers["Accept-Language"] == "en"
    assert ident.viewport == (800, 600)
    assert ident.locale == "fr"


def test_empty_catalogue_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        IdentityPool(profiles=())
