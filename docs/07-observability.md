# 07 — Observability

*Owner: Senior Developer + Architect.*

For an acquisition platform, observability *is* a feature: you must know whether collection
is healthy, fresh, and getting blocked. The `crawl_runs` + `ban_events` ledgers make
operational truth queryable — and make your anti-bot layer's effectiveness *visible*.

## 1. Pillars (v1 scope)

| Pillar | v1 | Later |
|--------|----|-------|
| **Logs** | `structlog` JSON, `run_id` + request context | Ship to a log platform |
| **Metrics** | Counters/gauges persisted in `crawl_runs`/`ban_events` + a `/metrics` summary | Prometheus/OTel export |
| **Health** | `GET /health` (liveness) + `GET /health/sources` (per-source freshness + ban status) | Uptime monitor + alerts |

## 2. Health model

```mermaid
graph TD
    H["GET /health"] --> L{process up + Postgres reachable?}
    L -- yes --> OK[200]
    L -- no --> DOWN[503]
    HS["GET /health/sources"] --> Q[latest CrawlRun per source]
    Q --> PS{per source}
    PS --> C1[last success age vs stale_after]
    PS --> C2[last run status]
    PS --> C3[recent ban_rate]
    C1 --> AGG[healthy | stale | degraded | failing]
    C2 --> AGG
    C3 --> AGG
    AGG --> RESP[200 per-source + overall]
```

`/health/sources` answers "is our data fresh and are we getting blocked?" in one call — the
operational heartbeat.

## 3. Log / never-log

**Log (structured):** crawl lifecycle (`run_id`, source, status, items_ok/rejected,
timings); each `BanEvent` (kind, status, action_taken); request summaries (method, host,
status, duration, proxy id — not credentials); API requests.

**Never log:** proxy credentials, tokens, cookies/session secrets, full upstream bodies
(only sizes/markers). A redaction list enforces this.

## 4. Acquisition metrics (the important part)

Derived from the ledgers (see `docs/04` §5):

| Metric | Type | Meaning |
|--------|------|---------|
| `crawl_runs_total{source,status}` | counter | successes/partials/failures |
| `items_ok` / `items_rejected{source}` | gauge | pipeline yield & quality |
| `ban_events_total{source,kind}` | counter | rate_limited/blocked/captcha/empty |
| `ban_rate{source}` | gauge | ban events ÷ requests — **headline resilience KPI** |
| `identity_rotations_total` / `proxy_rotations_total` | counter | recovery activity |
| `backoff_seconds_total` / `request_retries_total` | counter | politeness/recovery cost |
| `proxy_health{proxy}` | gauge | per-proxy success rate |
| `source_staleness_seconds{source}` | gauge | freshness vs. `stale_after` |

## 5. What the dashboard shows (observability the user/reviewer sees)

- Per-product price history charts (the product value).
- A **crawler-health panel**: last run per source, freshness, `ban_rate` trend,
  identity/proxy rotations, items ok vs rejected.

Showing `ban_rate` drop as rotation kicks in is the visible, demo-able proof the resilience
layer works — great in an interview.

## 6. Runbook stubs (fill in as built)
- **Ban rate spiking on a source:** inspect recent `ban_events.kind`; if `captcha`/`blocked`
  rising, lower rate / expand identity or proxy pool / back off longer; confirm the source
  isn't simply down.
- **Data stale:** check scheduler alive; check Postgres; check `crawl_runs` for repeated
  failures; re-run `uv run acquire-intel crawl <source>`.
- **items_rejected spiking:** likely source-format drift — compare against fixtures, update
  the extractor + fixtures (the gate correctly refused to store garbage).
