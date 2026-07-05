# Milestones — Definition of Done

Each milestone is demoable and verified: acceptance criteria met, tests green (incl. harness
where relevant), and observed running (`docs/06`).

## M0 — Foundation
- [ ] uv project (src layout), `pyproject.toml`, ruff + mypy configured, CLI entrypoint stub.
- [ ] `docker-compose.yml` with Postgres; `config/` via pydantic-settings (fail-fast); `.env.example`.
- [ ] Scrapy project skeleton wired into the package; `uv run acquire-intel --help` works.
- [ ] SQLAlchemy + Alembic baseline migration; `GET /health` (Flask) 200/503 by DB reachability.
- [ ] CI: uv sync → ruff → mypy → pytest (with Postgres service).
**DoD:** `docker compose up` + `uv run` boot; `/health` reflects DB; CI green on a trivial PR.

## M1 — First vertical slice (REST)
- [ ] `SourceExtractor` protocol + `RawProduct` pydantic model; parity with contracts.
- [ ] A **REST** extractor with pagination + rate-limit handling; fixtures (valid + malformed).
- [ ] Pipeline: pydantic validation → normalize (Decimal money+currency, canonical id) → dedup.
- [ ] Persist: `products` upsert + append `price_observations`; open/close `crawl_runs`.
- [ ] `GET /products`, `GET /products/:id/price-history` with `dataAsOf` + per-point `capturedAt`.
**DoD:** crawl the REST source → observations in Postgres → API returns them with freshness.

## M2 — More techniques
- [ ] **HTML** extractor via Playwright (JS-rendered fixture/page) under the same contract.
- [ ] **GraphQL** extractor (query build + cursor pagination) under the same contract.
- [ ] Fixtures + tests for both; both feed the identical pipeline/storage.
**DoD:** all three kinds (REST/HTML/GraphQL) produce canonical products from fixtures; tests green.

## M3 — Resilience (centerpiece)
- [ ] Proxy pool manager (health/cooldown; works with zero proxies).
- [ ] Coherent identity/fingerprint/header/cookie rotation.
- [ ] Adaptive throttle (AutoThrottle + per-domain caps), backoff+jitter, per-domain circuit-breaker.
- [ ] Ban/anti-bot classifier → `ban_events`; blocked responses never reach extractors.
- [ ] **Adversarial mock harness** with all scenarios; data-quality gates (volume/range/continuity).
**DoD:** every harness scenario green; ban events recorded; **0 garbage persisted**; ban-rate metric emitted.

## M4 — Intelligence + hardening
- [ ] Price history queries + **deals** (drops vs. own history); change/selector-drift detection.
- [ ] Flask dashboard: per-product price charts + crawler-health panel (ban-rate, freshness).
- [ ] Scheduler (APScheduler) + token-gated `POST /admin/crawl` + CLI.
- [ ] Monitoring endpoints/metrics; README with a 5-minute demo script; CI/CD polished.
**DoD:** a reviewer can boot it, run a crawl (harness or friendly source), and see charts +
health; all gates green; security checklist (`docs/08` §8) passes.
