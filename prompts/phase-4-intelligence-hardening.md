# Phase 4 — Intelligence + Hardening Prompts

Make the engineering legible and the product demoable. Governing specs: `specs/openapi.yaml`,
`docs/07`, `docs/08`, ADR-0007.

---

## T4.1 — Price history + deals
```
Task T4.1. Read: specs/openapi.yaml (getDeals), docs/03.
Goal: analytics/ — per-product price history queries; deals = significant drops vs a product's
own history; implement GET /deals per spec.
Verify: deterministic drop computation on fixtures; spec-conformant endpoint (integration
test).
```

## T4.2 — Change / selector-drift detection
```
Task T4.2. Read: docs/04 §3, PRD FR-16.
Goal: detect when a source's output shape/volume shifts and flag the run (alert, don't crash).
Verify: a drifted fixture produces a flagged run + rejected items, not a silent bad crawl.
```

## T4.3 — Dashboard
```
Task T4.3. Read: docs/adr/0007, docs/07 §5.
Goal: Jinja + Chart.js dashboard served by Flask: per-product price chart + a crawler-health
panel (ban-rate trend, freshness, items ok/rejected, identity/proxy rotations).
Verify: view tests + run it and show the charts + health panel.
```

## T4.4 — /health/sources + metrics
```
Task T4.4. Read: specs/openapi.yaml (getSourceHealth), docs/07 §2 & §4.
Goal: per-source health (healthy/degraded/stale/failing) derived from crawl_runs + stale_after
+ recent ban_rate; expose the metrics catalog.
Verify: integration tests over seeded crawl_runs covering each classification.
```

## T4.5 — Scheduler + admin crawl
```
Task T4.5. Read: docs/adr/0007, docs/08 §4, specs/openapi.yaml (triggerCrawl).
Goal: APScheduler per-source schedules calling the same crawl orchestration; token-gated POST
/admin/crawl (Bearer ADMIN_TOKEN, rate-limited); CLI parity. One orchestration callable by
scheduler, CLI, and HTTP.
Verify: integration tests — scheduled tick triggers a crawl; no token → 401; token → 202;
manual trigger shows a recorded run.
```

## T4.6 — Demo & CI/CD polish
```
Task T4.6. Read: plan/milestones.md (M4), docs/06 §6, docs/08 §8.
Goal: README with a 5-minute demo script (docker compose up → run a harness-backed crawl →
open the dashboard → see price charts + ban-rate dropping as identities rotate → hit the API).
Ensure CI runs the full suite + pip-audit. Confirm the security checklist (docs/08 §8).
Verify: dry-run the README steps on a fresh clone to a working demo; CI green. (portfolio gate)
```

## Phase 4 gate
A reviewer can boot it, run a crawl, and see charts + crawler health; scheduler + admin work;
CI/CD green; security checklist passes. Update backlog + CLAUDE.md status → v1 portfolio-ready.
```
