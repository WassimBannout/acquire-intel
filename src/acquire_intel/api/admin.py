"""Token-gated on-demand crawl trigger: ``POST /admin/crawl`` (T4.5, openapi ``triggerCrawl``).

The only write endpoint. It is gated by ``Authorization: Bearer <ADMIN_TOKEN>`` (constant-time
compare) and rate-limited per app (docs/08 §4), then delegates to the shared
:func:`acquire_intel.acquisition.orchestrator.trigger_crawl` — the same orchestration the scheduler
and CLI use — and returns ``202`` with the launched ``running`` runs. No anonymous caller can start
a crawl. Body: ``{"source": "<id>"}`` to crawl one source, or omit it to crawl all registered ones.
"""

from __future__ import annotations

import hmac
import time
from collections import deque
from typing import TYPE_CHECKING

from flask import Blueprint, current_app, jsonify, request
from pydantic import BaseModel, ConfigDict, ValidationError

from acquire_intel.acquisition.orchestrator import UnknownSourceError, trigger_crawl
from acquire_intel.api.errors import ProblemError
from acquire_intel.api.serializers import CrawlAcceptedResponse, CrawlRunOut
from acquire_intel.config import get_settings

if TYPE_CHECKING:
    from flask import Response

    from acquire_intel.acquisition.orchestrator import TriggeredRun

admin_bp = Blueprint("admin", __name__)

_BEARER = "Bearer "


class RateLimiter:
    """A fixed-window-free sliding-window limiter: at most ``max_calls`` per ``per_seconds``."""

    def __init__(self, max_calls: int, per_seconds: float) -> None:
        self._max = max_calls
        self._per = per_seconds
        self._calls: deque[float] = deque()

    def allow(self, *, now: float | None = None) -> bool:
        """Record a call and return whether it is within the limit."""
        now = time.monotonic() if now is None else now
        while self._calls and now - self._calls[0] >= self._per:
            self._calls.popleft()
        if len(self._calls) >= self._max:
            return False
        self._calls.append(now)
        return True


class _CrawlRequest(BaseModel):
    """The (optional) request body — an explicit source, or omit for all sources."""

    model_config = ConfigDict(extra="forbid")
    source: str | None = None


def _limiter() -> RateLimiter:
    """The per-app rate limiter (lazily built from config; isolated per Flask app)."""
    limiter = current_app.extensions.get("admin_rate_limiter")
    if not isinstance(limiter, RateLimiter):
        limiter = RateLimiter(get_settings().admin_rate_limit_per_minute, 60.0)
        current_app.extensions["admin_rate_limiter"] = limiter
    return limiter


def _authorized() -> bool:
    """True iff the request carries a valid ``Authorization: Bearer <ADMIN_TOKEN>``."""
    header = request.headers.get("Authorization", "")
    if not header.startswith(_BEARER):
        return False
    return hmac.compare_digest(header[len(_BEARER) :], get_settings().admin_token)


def _run_out(run: TriggeredRun) -> CrawlRunOut:
    """A just-triggered (``running``) run — item counts are unknown until it closes."""
    return CrawlRunOut(id=run.id, source=run.source, status=run.status, started_at=run.started_at)


@admin_bp.post("/admin/crawl")
def trigger() -> tuple[Response, int]:
    """Trigger an on-demand crawl (admin only); returns 202 with the launched runs."""
    if not _authorized():
        raise ProblemError(401, "Unauthorized", "Missing or invalid admin token")
    if not _limiter().allow():
        raise ProblemError(429, "Too Many Requests", "Admin crawl rate limit exceeded")
    try:
        payload = _CrawlRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        raise ProblemError(400, "Invalid request", "body must be {source?: string}") from None

    source_ids = [payload.source] if payload.source else None
    try:
        runs = trigger_crawl(source_ids)
    except UnknownSourceError as exc:
        detail = f"No registered source {exc.source_id!r}"
        raise ProblemError(404, "Unknown source", detail) from exc

    body = CrawlAcceptedResponse(accepted=True, runs=[_run_out(r) for r in runs])
    return jsonify(body.model_dump(by_alias=True, mode="json")), 202
