"""Coherent identity bundles + a rotating pool (T3.4, ADR-0005/0011, docs/04 §2.2).

An **identity** is a *coherent* bundle: a User-Agent plus the header profile, cookie jar, and
(for Playwright) viewport/locale that a real instance of that browser would send. Coherence is
the point — a Chrome User-Agent paired with Firefox ``Accept`` headers, or Chrome ``sec-ch-ua``
client hints with a Firefox UA, is itself a bot signal (docs/04 §2.2). So the catalogue below
pairs each UA with headers that *match* it, and rotation swaps a whole bundle at once, never a
lone field.

This module is pure data + a small state machine (no Scrapy, no I/O): the pool hands out the
current identity and rotates to the next on demand, deterministically, so it is unit-testable.
The Scrapy wiring — stamping the identity onto a request and rotating on a ban — lives in
:mod:`.middleware`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class BrowserProfile:
    """A coherent browser fingerprint: a UA and the headers/viewport that browser really sends."""

    name: str
    user_agent: str
    headers: Mapping[str, str]
    viewport: tuple[int, int]
    locale: str


@dataclass(frozen=True)
class Identity:
    """A live identity: a :class:`BrowserProfile` bound to a rotation ``generation``.

    ``key`` is unique per (profile, generation) and doubles as the Scrapy cookie-jar key, so each
    rotation gets a **fresh** cookie jar — a rotated identity never carries the previous one's
    cookies (that would leak the bundle you just abandoned).
    """

    key: str
    profile: BrowserProfile

    @property
    def user_agent(self) -> str:
        return self.profile.user_agent

    @property
    def headers(self) -> Mapping[str, str]:
        return self.profile.headers

    @property
    def viewport(self) -> tuple[int, int]:
        return self.profile.viewport

    @property
    def locale(self) -> str:
        return self.profile.locale


def _headers(**pairs: str) -> Mapping[str, str]:
    """A read-only header mapping (so a shared profile can't be mutated by a stamping caller)."""
    return MappingProxyType(dict(pairs))


# A small catalogue of *coherent* desktop browser bundles. Each UA is matched by the identity
# headers that browser genuinely emits (Chromium sends ``sec-ch-ua`` client hints; Firefox/Safari
# do not), so rotating between them stays believable. Realistic pools are finite — a handful of
# coherent bundles is enough to reset a per-identity budget (the harness keys on the User-Agent).
#
# Deliberately *not* stamped: ``Accept`` and ``Accept-Encoding``. Content negotiation belongs to
# the request (a GraphQL ``JsonRequest`` needs ``application/json``), and Accept-Encoding belongs
# to Scrapy's HttpCompressionMiddleware, which advertises exactly the codecs it can decode — a
# forced ``br`` we can't decompress would corrupt the body and fool the ban classifier. We manage
# only the pure identity/fingerprint signals (UA, language, client hints).
_DEFAULT_PROFILES: tuple[BrowserProfile, ...] = (
    BrowserProfile(
        name="chrome-win",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        headers=_headers(
            **{
                "Accept-Language": "en-US,en;q=0.9",
                "sec-ch-ua": '"Chromium";v="125", "Google Chrome";v="125", "Not.A/Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }
        ),
        viewport=(1920, 1080),
        locale="en-US",
    ),
    BrowserProfile(
        name="chrome-mac",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like "
            "Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        headers=_headers(
            **{
                "Accept-Language": "en-US,en;q=0.9",
                "sec-ch-ua": '"Chromium";v="125", "Google Chrome";v="125", "Not.A/Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            }
        ),
        viewport=(1680, 1050),
        locale="en-US",
    ),
    BrowserProfile(
        name="firefox-win",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0"
        ),
        # Firefox sends no sec-ch-ua client hints — including them would be incoherent.
        headers=_headers(**{"Accept-Language": "en-US,en;q=0.5"}),
        viewport=(1920, 1080),
        locale="en-US",
    ),
    BrowserProfile(
        name="firefox-linux",
        user_agent="Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
        headers=_headers(**{"Accept-Language": "en-US,en;q=0.5"}),
        viewport=(1600, 900),
        locale="en-US",
    ),
    BrowserProfile(
        name="safari-mac",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like "
            "Gecko) Version/17.4 Safari/605.1.15"
        ),
        headers=_headers(**{"Accept-Language": "en-US,en;q=0.9"}),
        viewport=(1440, 900),
        locale="en-US",
    ),
)


@dataclass
class IdentityPool:
    """Hands out the current identity and rotates to the next coherent bundle on demand.

    Rotation is round-robin over the catalogue with a monotonically increasing ``generation``, so
    the cookie-jar key is always fresh even once the profiles wrap around. Deterministic (ordered,
    no RNG) so tests can assert an exact rotation sequence.
    """

    profiles: Sequence[BrowserProfile] = _DEFAULT_PROFILES
    _index: int = 0
    _generation: int = 0
    _current: Identity = field(init=False)

    def __post_init__(self) -> None:
        if not self.profiles:
            raise ValueError("IdentityPool needs at least one BrowserProfile")
        self._current = self._build()

    def _build(self) -> Identity:
        profile = self.profiles[self._index]
        return Identity(key=f"{profile.name}#{self._generation}", profile=profile)

    @property
    def current(self) -> Identity:
        """The identity to present now (stable until :meth:`rotate` is called)."""
        return self._current

    def rotate(self) -> Identity:
        """Advance to the next coherent bundle (fresh cookie jar) and return it."""
        self._index = (self._index + 1) % len(self.profiles)
        self._generation += 1
        self._current = self._build()
        return self._current
