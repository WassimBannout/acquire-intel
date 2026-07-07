"""Crawler-health summary for the dashboard panel (T4.3, docs/07 §5).

Pure assembly of the crawler-health view from the crawl-run ledger + ban audit trail. Given a
source's recent runs (newest-first) and its rotation tally, :func:`summarize_source` produces a
compact :class:`SourceHealth`: last run status, freshness vs. ``stale_after``, item yield, ban
count, identity/proxy rotations, and a ban-events trend for a sparkline.

I/O-free and DB-free — the route (``api/dashboard.py``) maps ORM rows → :class:`RunPoint`s so
every derivation is unit-testable without a database. The formal healthy/degraded/stale/failing
classification and the ``/health/sources`` endpoint + metrics catalog are T4.4; this stays
presentation-focused (raw last status + a freshness flag).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

# Runs that actually committed data — a source's freshness is judged from these (docs/07 §2).
_COMMITTED = frozenset({"success", "partial"})
# Terminal statuses that committed no data but are not a hard failure (data-quality signals).
_DEGRADED_STATUSES = frozenset({"partial", "quarantined", "flagged"})

# The four per-source health states (specs/openapi.yaml ``SourceHealth.status``), ordered by
# severity: a source's data promise is "fresh, complete data" — losing freshness (``stale``) is
# more severe than noisy-but-flowing data (``degraded``); a hard error is the worst.
HealthStatus = Literal["healthy", "degraded", "stale", "failing"]
_SEVERITY: dict[HealthStatus, int] = {"healthy": 0, "degraded": 1, "stale": 2, "failing": 3}


@dataclass(frozen=True)
class RunPoint:
    """One crawl run, reduced to what the health panel needs (a row of ``crawl_runs``)."""

    status: str
    started_at: datetime
    finished_at: datetime | None
    items_ok: int
    items_rejected: int
    ban_events: int
    requests: int = 0  # from ``crawl_runs.timings.requests``; denominator of the ban-rate


@dataclass(frozen=True)
class SourceHealth:
    """The per-source crawler-health view rendered on the dashboard."""

    source_id: str
    last_status: str | None  # latest run's terminal status (None → no runs yet)
    last_run_at: datetime | None  # latest run's finish (or start, if still running)
    last_success_at: datetime | None  # most recent committed run's finish
    items_ok: int  # latest run
    items_rejected: int  # latest run
    ban_events: int  # latest run's ban count
    rotations: int  # rotate_identity + rotate_proxy across the recent window
    stale: bool  # last success older than stale_after (or never succeeded, given history)
    trend: list[int]  # ban_events per recent run, oldest→newest (sparkline)
    total_runs: int  # runs in the recent window


def summarize_source(
    source_id: str,
    runs: Sequence[RunPoint],
    *,
    rotations: int,
    stale_after_seconds: int | None,
    now: datetime,
) -> SourceHealth:
    """Reduce a source's recent runs (newest-first) to a :class:`SourceHealth` view.

    ``stale`` is true when the most recent committed (``success``/``partial``) run is older than
    ``stale_after_seconds`` — or when runs exist but none committed (we have no fresh data). With
    no runs at all, or no staleness budget, ``stale`` is false (nothing to be stale about yet).
    """
    if not runs:
        return SourceHealth(
            source_id=source_id,
            last_status=None,
            last_run_at=None,
            last_success_at=None,
            items_ok=0,
            items_rejected=0,
            ban_events=0,
            rotations=rotations,
            stale=False,
            trend=[],
            total_runs=0,
        )

    latest = runs[0]
    last_success_at = next(
        (r.finished_at for r in runs if r.status in _COMMITTED and r.finished_at is not None),
        None,
    )

    if stale_after_seconds is None:
        stale = False
    elif last_success_at is None:
        stale = True  # runs happened but none committed — data isn't fresh
    else:
        stale = (now - last_success_at).total_seconds() > stale_after_seconds

    return SourceHealth(
        source_id=source_id,
        last_status=latest.status,
        last_run_at=latest.finished_at or latest.started_at,
        last_success_at=last_success_at,
        items_ok=latest.items_ok,
        items_rejected=latest.items_rejected,
        ban_events=latest.ban_events,
        rotations=rotations,
        stale=stale,
        trend=[r.ban_events for r in reversed(runs)],
        total_runs=len(runs),
    )


@dataclass(frozen=True)
class SourceHealthSummary:
    """A source's classified health (``specs/openapi.yaml`` ``SourceHealth``)."""

    source: str
    status: HealthStatus
    last_success_at: datetime | None
    last_run_status: str | None
    ban_rate: float | None  # recent ban events / requests (None when no requests seen)
    stale_after_seconds: int


def _last_success_at(runs: Sequence[RunPoint]) -> datetime | None:
    return next(
        (r.finished_at for r in runs if r.status in _COMMITTED and r.finished_at is not None),
        None,
    )


def classify_source(
    source: str,
    runs: Sequence[RunPoint],
    *,
    stale_after_seconds: int,
    now: datetime,
    degraded_ban_rate: float,
    fail_ban_rate: float,
) -> SourceHealthSummary:
    """Classify a source ``healthy|degraded|stale|failing`` from its recent runs (newest-first).

    Precedence (worst wins, docs/07 §2): **failing** if the latest run errored or the recent
    ban-rate is at/above ``fail_ban_rate``; else **stale** if the freshest committed run is older
    than ``stale_after_seconds`` (the source stopped producing fresh data); else **degraded** on a
    quality signal (partial/quarantined/flagged, an elevated ban-rate, or no committed run yet);
    else **healthy**. A registered source with no runs is ``stale`` (no fresh data yet).
    """
    if not runs:
        return SourceHealthSummary(
            source=source,
            status="stale",
            last_success_at=None,
            last_run_status=None,
            ban_rate=None,
            stale_after_seconds=stale_after_seconds,
        )

    latest = runs[0]
    last_success_at = _last_success_at(runs)
    total_bans = sum(r.ban_events for r in runs)
    total_requests = sum(r.requests for r in runs)
    ban_rate = (total_bans / total_requests) if total_requests > 0 else None
    stale = last_success_at is not None and (now - last_success_at).total_seconds() > (
        stale_after_seconds
    )

    if latest.status == "failed" or (ban_rate is not None and ban_rate >= fail_ban_rate):
        status: HealthStatus = "failing"
    elif stale:
        status = "stale"
    elif (
        latest.status in _DEGRADED_STATUSES
        or (ban_rate is not None and ban_rate >= degraded_ban_rate)
        or last_success_at is None
    ):
        status = "degraded"
    else:
        status = "healthy"

    return SourceHealthSummary(
        source=source,
        status=status,
        last_success_at=last_success_at,
        last_run_status=latest.status,
        ban_rate=ban_rate,
        stale_after_seconds=stale_after_seconds,
    )


def overall_status(statuses: Iterable[HealthStatus]) -> HealthStatus:
    """Roll per-source statuses up to the worst one (``healthy`` when there are no sources)."""
    return max(statuses, key=lambda s: _SEVERITY[s], default="healthy")
