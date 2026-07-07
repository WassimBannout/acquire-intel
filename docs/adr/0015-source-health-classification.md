# ADR-0015: Per-source health classification + the ledger-derived metrics catalog

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** Pipeline/Monitoring Engineer, Architect
- **Related:** ADR-0006 (ledgers), ADR-0007 (Flask read surface), docs/07 §2 & §4, PRD FR-10,
  specs/openapi.yaml (`getSourceHealth`)

## Context
FR-10 / docs/07 want the operational heartbeat "is our data fresh and are we getting blocked?"
answerable in one call. `specs/openapi.yaml` fixes the answer's shape: `GET /health/sources`
returns a per-source `status ∈ {healthy, degraded, stale, failing}` + an `overall` rollup, plus
`lastSuccessAt`, `lastRunStatus`, `banRate`, `staleAfterSeconds`. The signals must come only from
what the ledgers already record (`crawl_runs`, `ban_events`) — no new collection. The headline
KPI, `ban_rate = ban events / requests`, needs a per-run request count that wasn't yet persisted.

## Decision
Classify each source from its **recent N runs** with a pure function
(`analytics/health.py::classify_source`) and expose the metrics catalog as a JSON summary.

- **Signals (per source, over the last `HEALTH_RECENT_RUNS` runs, default 5):** the latest run's
  status; `last_success_at` = newest `finished_at` whose status is committed (`success`/`partial`);
  `ban_rate` = Σ`ban_events` ÷ Σ`requests` (None when no requests seen); `stale` = `last_success_at`
  older than the source's `stale_after_seconds`.
- **Classification precedence (worst wins):** **failing** if the latest run is `failed` or
  `ban_rate ≥ HEALTH_FAIL_BAN_RATE` (0.5) → else **stale** if `stale` → else **degraded** on a
  quality signal (latest status `partial`/`quarantined`/`flagged`, `ban_rate ≥
  HEALTH_DEGRADED_BAN_RATE` (0.2), or *no committed run yet*) → else **healthy**. A registered
  source with **no runs** is `stale` (no fresh data yet).
- **Severity order** (used both for that per-source precedence and the `overall` rollup):
  `healthy < degraded < stale < failing`. `stale` outranks `degraded` because losing freshness
  breaks the platform's core promise (fresh price data), whereas a degraded source is still
  flowing. `overall` = the worst source (`healthy` when there are none).
- **Persist `requests` per run:** the runner writes `crawl_runs.timings = {"requests": N}` on close
  (from Scrapy's `downloader/request_count`) — `timings` is JSONB, so no migration. This is the
  `ban_rate` denominator.
- **`GET /metrics`:** a ledger-derived JSON summary of the docs/07 §4 catalog —
  `crawl_runs_total{source,status}`, `ban_events_total{source,kind}` (ban rows carry only
  `run_id`, so source is a join to `crawl_runs`), `ban_rate`, latest `items_ok`/`items_rejected`,
  `source_staleness_seconds`, and identity/proxy `rotations` (from `ban_events.action_taken`).
  Not in `openapi.yaml` (it's a summary, not a typed contract); shape documented in-module.

Both routes stay thin (ADR-0007): the classifier is pure and unit-tested; routes only map rows →
`RunPoint`s, call it, and serialize through camelCase API models.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| Recent-N-runs window + pure classifier (chosen) | Deterministic, unit-testable without a DB; bounded query; reuses existing ledgers | Window size is a tuning knob; a burst just outside the window is missed |
| Time-window (e.g. last 24h) for ban-rate | Calendar-intuitive | Non-deterministic in tests; empty windows for slow sources; needs `now` everywhere |
| Store health as a materialized column on `sources` | O(1) read | Staleness/refresh problem; duplicates ledger truth; write coupling |
| Prometheus/OTel exporter instead of `/metrics` JSON | Standard, scrapeable | Extra infra for v1; docs/07 scopes exporters to "later" |

## Consequences
- **Positive:** one call classifies every source deterministically; `ban_rate` (the resilience KPI)
  is real (persisted requests), not estimated; the dashboard's crawler-health panel (T4.3) and this
  endpoint read the same pure logic; adding a metric is a repo aggregate + a dict key.
- **Trade-offs accepted:** a fixed *run-count* window (not time) — chosen for test determinism;
  `overall` is a single worst-status rollup, not a weighted score. `lastRunStatus` is serialized as
  the raw ledger status (which now includes `quarantined`/`flagged`) even though the openapi enum
  lists only four — we report truth over a stale enum rather than lie.
- **Follow-ups:** proxy-health + backoff/retry counters (docs/07 §4) still live in per-run Scrapy
  stats, not the ledger; persist them if `/metrics` needs to expose them. A captcha-only crawl that
  "finished" is still ledgered `success` (T3.6 status mapping) — a separate ledger-accuracy question,
  not this ADR's.

## Notes
Thresholds are config (`HEALTH_RECENT_RUNS`, `HEALTH_DEGRADED_BAN_RATE`, `HEALTH_FAIL_BAN_RATE`);
never hardcode them in routes. Any new health input must be a signal already in the ledgers (or
newly persisted there) so the classifier stays pure and DB-free to test.
