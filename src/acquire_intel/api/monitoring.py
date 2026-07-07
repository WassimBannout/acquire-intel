"""Observability read surface: ``GET /health/sources`` + ``GET /metrics`` (T4.4, docs/07 §2 & §4).

``/health/sources`` classifies each source ``healthy | degraded | stale | failing`` from its recent
``crawl_runs`` (freshness vs. ``stale_after`` + last-run status + recent ban-rate) and rolls them up
to an ``overall`` — the operational "is our data fresh and are we getting blocked?" heartbeat.
``/metrics`` exposes the ledger-derived metrics catalog (docs/07 §4) as a JSON summary.

Routes stay thin (ADR-0007): the classification is the pure
:func:`acquire_intel.analytics.health.classify_source`; here we only map ``crawl_runs`` rows →
``RunPoint``s, call it, and serialize.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify

from acquire_intel.analytics.health import (
    RunPoint,
    SourceHealthSummary,
    classify_source,
    overall_status,
)
from acquire_intel.api.serializers import SourceHealthOut, SourceHealthResponse
from acquire_intel.config import get_settings
from acquire_intel.storage import (
    BanEventRepository,
    CrawlRunRepository,
    SourceRepository,
    session_scope,
)

if TYPE_CHECKING:
    from flask import Response
    from sqlalchemy.orm import Session

    from acquire_intel.config import Settings
    from acquire_intel.storage import CrawlRun

monitoring_bp = Blueprint("monitoring", __name__)


def _run_point(run: CrawlRun) -> RunPoint:
    """Map a ``crawl_runs`` row to the pure classifier's input (requests from ``timings``)."""
    requests = int((run.timings or {}).get("requests", 0))
    return RunPoint(
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        items_ok=run.items_ok,
        items_rejected=run.items_rejected,
        ban_events=run.ban_events,
        requests=requests,
    )


def _collect(
    session: Session, cfg: Settings, now: datetime
) -> list[tuple[SourceHealthSummary, CrawlRun | None]]:
    """Classify every registered source; return each summary + its latest run (for metrics)."""
    sources = SourceRepository(session)
    runs = CrawlRunRepository(session)
    thresholds = sources.stale_after_for(set(sources.list_ids()))
    collected: list[tuple[SourceHealthSummary, CrawlRun | None]] = []
    for source_id in sources.list_ids():
        recent = runs.recent(source_id, limit=cfg.health_recent_runs)
        summary = classify_source(
            source_id,
            [_run_point(r) for r in recent],
            stale_after_seconds=thresholds.get(source_id, 0),
            now=now,
            degraded_ban_rate=cfg.health_degraded_ban_rate,
            fail_ban_rate=cfg.health_fail_ban_rate,
        )
        collected.append((summary, recent[0] if recent else None))
    return collected


def _round_rate(rate: float | None) -> float | None:
    return round(rate, 4) if rate is not None else None


def _health_out(summary: SourceHealthSummary) -> SourceHealthOut:
    return SourceHealthOut(
        source=summary.source,
        status=summary.status,
        last_success_at=summary.last_success_at,
        last_run_status=summary.last_run_status,
        ban_rate=_round_rate(summary.ban_rate),
        stale_after_seconds=summary.stale_after_seconds,
    )


@monitoring_bp.get("/health/sources")
def source_health() -> Response:
    """Per-source freshness + collection/ban health, plus an overall rollup."""
    cfg = get_settings()
    now = datetime.now(UTC)
    with session_scope() as session:
        summaries = [summary for summary, _ in _collect(session, cfg, now)]
        payload = SourceHealthResponse(
            overall=overall_status([s.status for s in summaries]),
            sources=[_health_out(s) for s in summaries],
        )
    return jsonify(payload.model_dump(by_alias=True, mode="json"))


@monitoring_bp.get("/metrics")
def metrics() -> Response:
    """The ledger-derived metrics catalog (docs/07 §4) as a JSON summary."""
    cfg = get_settings()
    now = datetime.now(UTC)
    with session_scope() as session:
        collected = _collect(session, cfg, now)
        run_counts = CrawlRunRepository(session).status_counts_by_source()
        ban_kinds = BanEventRepository(session).kind_counts_by_source()
        actions = BanEventRepository(session).action_totals()

        per_source: dict[str, object] = {}
        for summary, latest in collected:
            sid = summary.source
            staleness = (
                round((now - summary.last_success_at).total_seconds(), 1)
                if summary.last_success_at is not None
                else None
            )
            per_source[sid] = {
                "status": summary.status,
                "crawlRunsTotal": run_counts.get(sid, {}),
                "itemsOk": latest.items_ok if latest is not None else 0,
                "itemsRejected": latest.items_rejected if latest is not None else 0,
                "banEventsTotal": ban_kinds.get(sid, {}),
                "banRate": _round_rate(summary.ban_rate),
                "stalenessSeconds": staleness,
            }
        payload = {
            "generatedAt": now.isoformat(),
            "sources": per_source,
            "rotations": {
                "identity": actions.get("rotate_identity", 0),
                "proxy": actions.get("rotate_proxy", 0),
            },
        }
    return jsonify(payload)
