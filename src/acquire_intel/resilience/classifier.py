"""Ban / anti-bot response classification (T3.2, ADR-0005, docs/04 §2.5).

The "never cache garbage" gate: **every** response is labelled *before* it can reach an
extractor. A pure function over the signals a single response carries — HTTP status, known
block/WAF/CAPTCHA markers in the body, and an empty/near-empty body — so it is deterministic and
fixture-testable without Scrapy or the network. The Scrapy wiring lives in :mod:`.middleware`.

Labels (``Classification``) are ``ok`` plus the four :data:`~acquire_intel.contracts.BanKind`
values, so a non-``ok`` label maps 1:1 to a recorded ``BanEvent``. Precedence is deliberate: a
challenge page can arrive as ``200`` or ``403``, so **CAPTCHA markers win over status**; then
``429`` → rate-limited, other non-2xx → blocked, and a ``2xx`` with an empty body → a silent
soft-ban.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from acquire_intel.contracts import BanAction, BanKind


class Classification(StrEnum):
    """The label assigned to a response. ``OK`` alone is safe to parse; the rest are bans."""

    OK = "ok"
    RATE_LIMITED = "rate_limited"
    BLOCKED = "blocked"
    CAPTCHA = "captcha"
    EMPTY = "empty"


# Case-insensitive substrings that betray a JS/CAPTCHA challenge interstitial (not real data).
_CAPTCHA_MARKERS: tuple[str, ...] = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "are you a robot",
    "verify you are human",
    "just a moment",
    "checking your browser",
    "cf-challenge",
    "challenge-form",
    "enable javascript and",
)

# Only scan the head of a body for markers — enough to catch an interstitial, bounded for speed.
_SCAN_LIMIT = 64 * 1024

# A non-``ok`` label maps 1:1 to a BanEvent kind (same wire values) and a recommended recovery
# action (docs/04 §2.5). The action is *policy*; T3.3/T3.4 execute it — this task only detects
# and gates. Kept as typed maps so the ``BanKind``/``BanAction`` literals stay mypy-checked.
_BAN_KIND: dict[Classification, BanKind] = {
    Classification.RATE_LIMITED: "rate_limited",
    Classification.BLOCKED: "blocked",
    Classification.CAPTCHA: "captcha",
    Classification.EMPTY: "empty",
}
_RECOMMENDED_ACTION: dict[Classification, BanAction] = {
    Classification.RATE_LIMITED: "backoff",  # honour Retry-After, then resume
    Classification.BLOCKED: "rotate_identity",  # a fresh identity/proxy
    Classification.CAPTCHA: "rotate_identity",  # a fresh identity, and flag
    Classification.EMPTY: "rotate_identity",  # soft-ban → retry as someone else
}


def classify(*, status: int, body: bytes) -> Classification:
    """Label one response from its status + body. Pure and deterministic."""
    text = body[:_SCAN_LIMIT].decode("utf-8", "ignore").lower()

    # A challenge can be served as 200 or 403 — its markers are the strongest signal.
    if any(marker in text for marker in _CAPTCHA_MARKERS):
        return Classification.CAPTCHA

    if status == 429:
        return Classification.RATE_LIMITED

    if 200 <= status < 300:
        # A 2xx with no body is a silent soft-ban — distinct from a legitimate empty JSON
        # array (e.g. an end-of-pagination ``{"products": []}``), which has a non-empty body.
        if not body.strip():
            return Classification.EMPTY
        return Classification.OK

    # Any other non-2xx (401/403/5xx/…) is treated as a block: not parseable data.
    return Classification.BLOCKED


def is_ban(classification: Classification) -> bool:
    """True for any non-``ok`` label (i.e. a response that must never reach an extractor)."""
    return classification is not Classification.OK


def ban_kind(classification: Classification) -> BanKind:
    """The ``BanKind`` for a non-``ok`` label (raises for ``OK``)."""
    return _BAN_KIND[classification]


def recommended_action(classification: Classification) -> BanAction:
    """The recovery action policy prescribes for a non-``ok`` label (raises for ``OK``)."""
    return _RECOMMENDED_ACTION[classification]
