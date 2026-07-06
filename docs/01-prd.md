# 01 — Product Requirements Document (PRD)

*Owner: Senior Product Manager. Companion: `docs/00-vision.md`.*

## 1. Summary

AcquireIntel is a Python data-acquisition platform that collects product & price data from
defended public web sources via HTML, REST, and GraphQL, applies a resilient anti-bot
collection layer, validates and normalizes into a canonical schema, persists an append-only
price-history time-series, and serves it through a Flask API + light dashboard.

## 2. Role-fit mapping (why this project, for this job)

This project is engineered to evidence a **Data Acquisition / Research Engineer** skill set.
Every feature traces to a hiring requirement:

| Target job requirement | Where the project proves it |
|------------------------|------------------------------|
| **Python** | Entire stack (Scrapy, Playwright, Flask, pydantic, SQLAlchemy) |
| **Scrapy** | Crawl backbone: scheduler, middlewares, item pipelines (FR-1, FR-8) |
| **Playwright / headless browser** | JS-rendered source extractor (FR-3) |
| **REST APIs** | REST extractor with pagination + rate-limit handling (FR-2) |
| **GraphQL APIs** | GraphQL extractor: query building + cursor pagination (FR-4) |
| **Anti-bot / adversarial collection** | Resilience layer + adversarial harness (FR-5, FR-6, FR-11) |
| **Networking: proxies, headers, cookies** | Proxy manager, identity/fingerprint rotation, session pools (FR-5) |
| **Scalable pipelines** | Validate → normalize → dedup → quality-gate → persist (FR-8, FR-9) |
| **Data-quality monitoring** | Quality gates + crawl-run health + metrics (FR-9, FR-10) |
| **CI/CD** | GitHub Actions, Docker, full test suite (NFR) |

## 3. Scope

### In scope (v1)
- Pluggable source extractors of three kinds: **HTML** (Scrapy+Playwright), **REST**,
  **GraphQL**.
- A resilient collection layer: proxy rotation, identity/fingerprint/header/cookie rotation,
  adaptive throttling, backoff/retry, ban detection.
- A local **adversarial mock server** that simulates rate limits, blocks, CAPTCHA/JS
  challenges, and cookie walls, for deterministic testing.
- Pipeline: pydantic validation → normalization → dedup → data-quality gates → Postgres.
- Append-only **price-history** time-series + canonical product projection.
- Flask API + light dashboard: products, price history, deals (biggest drops), health.
- Scheduled + on-demand (CLI/admin) collection.

### Out of scope (v1)
See `docs/00-vision.md` §Non-goals. Notably: auth-walled/PII data, streaming, ML pricing
models, multi-tenant SaaS, distributed multi-node crawling (single-node concurrent is v1).

## 4. Functional requirements

Priority: P0 launch-blocking, P1 important, P2 nice-to-have. IDs map to `plan/backlog.md`.

| ID | Pri | Requirement |
|----|-----|-------------|
| FR-1 | P0 | A Scrapy-based engine crawls a source, honoring a per-source config (rate, concurrency, robots policy). |
| FR-2 | P0 | A **REST** extractor collects products from a JSON/REST endpoint with pagination + rate-limit handling. |
| FR-3 | P0 | An **HTML** extractor collects from a JS-rendered page via Playwright. |
| FR-4 | P1 | A **GraphQL** extractor collects via a GraphQL endpoint (query construction + cursor pagination). |
| FR-5 | P0 | A **resilience layer** provides proxy rotation, identity (UA/header/fingerprint) rotation, adaptive throttle, exponential backoff+jitter, retry, and per-domain circuit-breaking. |
| FR-6 | P0 | **Ban/anti-bot detection** classifies responses (block page, CAPTCHA/JS challenge, empty, rate-limited) and reacts (rotate identity, back off) instead of storing them. |
| FR-7 | P0 | Every response is validated (pydantic) at the boundary; invalid → run fails/records, never persists. |
| FR-8 | P0 | A pipeline normalizes to a canonical `Product` + `PriceObservation` (Decimal money + currency) and dedups. |
| FR-9 | P0 | **Data-quality gates** (shape, range, volume, continuity) flag/quarantine anomalies; nothing garbage is stored silently. |
| FR-10 | P0 | Every crawl attempt is recorded as a `CrawlRun` (status, item count, ban events, timings) powering health & freshness. |
| FR-11 | P0 | The **adversarial mock harness** exercises the resilience layer deterministically (429/403/CAPTCHA/cookie-wall/rate-limit scenarios). |
| FR-12 | P0 | An append-only price-history time-series is queryable per product. |
| FR-13 | P1 | Flask API serves: products, per-product price history, top deals (drops), and health. |
| FR-14 | P1 | A light dashboard visualizes price history + a crawler-health panel. |
| FR-15 | P1 | Scheduled collection + an admin/CLI on-demand trigger per source. |
| FR-16 | P2 | Change/selector-drift detection alerts when a source's output shape shifts. |
| FR-17 | P2 | Deal detection: significant price drops vs. the product's own history. |

### Acceptance criteria (representative)

**FR-5/FR-6 — Resilience & ban detection**
- Against the adversarial harness returning `429 + Retry-After`, the collector waits/backs
  off and eventually succeeds; the run records the backoff events.
- Against a source that `403`-blocks a given identity after N requests, the collector
  rotates identity/proxy and continues; a blocked response is **never** yielded to the
  pipeline as data.
- A CAPTCHA/JS-challenge page is classified as a ban event, not parsed into a product.
- All of the above are covered by deterministic tests (no live site required).

**FR-9 — Data-quality gates**
- A run returning item volume outside ±X% of the previous run for that source is flagged
  and quarantined (not silently stored).
- Prices outside a plausible range, or non-`Decimal`/missing-currency, are rejected.

**FR-12/FR-13 — Price history**
- Repeated collections append immutable observations; the API returns a per-product time
  series with `capturedAt` and `sourceId` on every point.

## 5. Non-functional requirements

| Category | Requirement |
|----------|-------------|
| Resilience | A source failing/blocking must not crash the run or other sources; degrade to partial data + recorded failure. |
| Correctness | Invalid/blocked responses are never persisted. Money is `Decimal`+currency. Timestamps UTC. |
| Respectful crawling | `robots.txt` obeyed by default; polite per-domain rate limits; honest contact User-Agent. Exceptions documented (`docs/08`). |
| Observability | Structured logs; crawl-run ledger; per-source health, freshness, ban-rate, proxy-health metrics (`docs/07`). |
| Security | No secrets in repo; proxies/keys via env; admin trigger token-gated; input validated everywhere (`docs/08`). |
| Performance | Concurrent within a source (bounded); a full sample crawl completes in minutes locally. |
| Testability | Resilience proven against the adversarial harness; pure logic unit-tested; endpoints integration-tested (`docs/06`). |
| Portability | `docker compose up` brings up Postgres + app; reproducible with `uv`. |

## 6. Success metrics

| Metric | Target |
|--------|--------|
| Acquisition techniques demonstrated | 3 (HTML, REST, GraphQL) |
| Resilience scenarios covered by harness | ≥5 (429, 403-block, CAPTCHA, cookie-wall, rate-limit) |
| Garbage responses persisted | 0 |
| Sources pluggable via one extractor contract | 100% |
| Crawl-run health & freshness observable | Yes, per source |
| CI: lint + types + tests green | Required to merge |

## 7. Release plan (maps to `plan/roadmap.md`)

- **M0 Foundation** — repo, uv, Docker/Postgres, config, Scrapy skeleton, CI, health.
- **M1 First vertical slice** — one **REST** source end-to-end: collect → validate →
  normalize → persist → serve + freshness.
- **M2 More techniques** — **HTML (Playwright)** + **GraphQL** extractors under the same
  contract.
- **M3 Resilience + harness** — anti-bot layer + adversarial mock harness + ban detection +
  data-quality gates (the centerpiece).
- **M4 Intelligence + hardening** — price history/deals, dashboard, monitoring, scheduler,
  change detection, CI/CD polish.

## 8. Implementation status

*Snapshot as of 2026-07-06. Kept in sync with `plan/backlog.md` and the "Current status"
section of `CLAUDE.md`; those are the source of truth for task-level state.*

**Overall: M0 (Foundation) complete and gated; M1 (first REST slice) in progress — collect →
validate → normalize works in-memory; persistence next.** The platform is scaffolded end-to-end
— it boots, migrates, and answers `/health` — the canonical data contracts (`RawProduct` +
`Product`/`PriceObservation`/`Money`/`CrawlRun`/`BanEvent`) exist and are parity-tested, the
first concrete source (`demo_rest`) parses paginated JSON into `RawProduct`s, and the Scrapy
item pipeline validates → normalizes (Decimal money, canonical id, UTC capture) → dedups within
a run, rejecting/counting anything unmappable. The chain runs in memory but **nothing is
persisted or served yet**: what remains for M1 is persistence + the crawl-run ledger (T1.5), the
read API (T1.6), and the end-to-end crawl→DB→API wiring (T1.7).

### Milestone progress

| Milestone | State | Notes |
|-----------|-------|-------|
| **M0 Foundation** | ✅ Complete | Gate passed: `docker compose up` + `uv run` boot; `/health` reflects DB; strict ruff/mypy/pytest green; CI wired. |
| **M1 First vertical slice (REST)** | 🟡 In progress | T1.1–T1.4 ✅ done (contracts + REST extractor + normalize/dedup pipeline). Next: T1.5 persistence → T1.6 API → T1.7 E2E gate. |
| **M2 More techniques (HTML/GraphQL)** | ⬜ Not started | — |
| **M3 Resilience + harness** | ⬜ Not started | The centerpiece; unbuilt. |
| **M4 Intelligence + hardening** | ⬜ Not started | — |

### M1 progress (REST slice)

| Task | State | Notes |
|------|-------|-------|
| T1.1 — SourceExtractor contract + RawProduct | ✅ Done | `acquisition/extractor.py`: `RawProduct` pydantic model (`extra="forbid"`) + `runtime_checkable` `SourceExtractor` Protocol; parity-tested vs `raw-product.schema.json`. |
| T1.2 — Canonical models + contract parity | ✅ Done | `contracts.py`: `Money`(Decimal+currency, string-serialized), `Product`, `PriceObservation`, `CrawlRun`, `BanEvent`; UTC-normalizing datetime; parity + money/UTC/enum invariant tests green. |
| T1.3 — REST extractor | ✅ Done | `sources/demo_rest.py`: `DemoRestExtractor` (`kind="rest"`) walks a paginated Shopify-style `products.json` → `RawProduct`s; malformed/blocked page → nothing; fixtures + 12 tests green. |
| T1.4 — Pipeline: validate → normalize → dedup | ✅ Done | `pipeline/normalize.py` + `NormalizePipeline`: `RawProduct` → `Product` + `PriceObservation` (Decimal money, canonical id, currency fallback, UTC capture); in-run dedup keep-first; invalid rejected + counted. ADR-0010. |
| T1.5 — Persistence + crawl-run ledger | ⏳ Next | Upsert `products`, append immutable `price_observations`; open/close `crawl_runs` (status, items_ok/rejected). Postgres integration test. |
| T1.6 — GET /products + /price-history | ⬜ Todo | — |
| T1.7 — End-to-end REST slice | ⬜ Todo | M1 gate. |

### What M0 delivered (T0.1–T0.6, all ✅)

- **Scaffold** — uv project, `src/` layout with the eight concern-modules, ruff + mypy
  strict, `acquire-intel` CLI entrypoint.
- **Config & env boundary** — `config/` is the single env boundary (pydantic-settings,
  fail-fast `ConfigError`); `.env.example` ships every key; no `os.environ` elsewhere.
- **Storage baseline** — `docker-compose.yml` (Postgres 16); SQLAlchemy 2.0 models for
  `sources/products/price_observations/crawl_runs/ban_events` (+ indexes); Alembic baseline
  migration; a repository smoke test round-trips.
- **Scrapy skeleton** — Scrapy embedded in `acquisition/`, no-op spider, source-registry
  stub, `acquire-intel crawl <source>` wiring, structlog JSON logging carrying `run_id`.
- **Flask skeleton** — app factory, RFC 9457 problem+json handlers, `GET /health` (200/503
  by DB reachability), verified live.
- **CI** — GitHub Actions: `uv sync --locked` → ruff → format-check → mypy → alembic → pytest
  with a Postgres service container.

### Functional-requirement status

| FR | Status | Where it stands |
|----|--------|-----------------|
| FR-1 (Scrapy engine) | 🟡 Scaffolded | No-op spider + CLI wiring exist; per-source config/crawl behavior pending M1. |
| FR-2 (REST extractor) | 🟡 Substantial | Contract + `RawProduct` (T1.1) and a concrete paginated-JSON REST extractor `demo_rest` (T1.3) parse fixtures → `RawProduct`s; not yet wired to pipeline/persistence (T1.4–T1.7). |
| FR-3 (HTML/Playwright) | 🔴 Not started | M2. |
| FR-4 (GraphQL extractor) | 🔴 Not started | M2. |
| FR-5 (resilience layer) | 🔴 Not started | M3 centerpiece. |
| FR-6 (ban detection) | 🔴 Not started | M3. |
| FR-7 (boundary validation) | 🟡 Substantial | Config + extractor output validated via `RawProduct` (`extra="forbid"`, T1.1); the pipeline re-asserts the boundary and rejects+counts unmappable items, never persisting garbage (T1.4). Wired into a real crawl at T1.7. |
| FR-8 (normalize + dedup pipeline) | 🟡 Substantial | Scrapy item pipeline normalizes `RawProduct` → `Product` + `PriceObservation` (Decimal money, canonical id, currency fallback) and dedups within a run, rejecting/counting invalid (T1.2/T1.4, ADR-0010); persisting the output is T1.5. |
| FR-9 (data-quality gates) | 🔴 Not started | M3. |
| FR-10 (crawl-run ledger) | 🟡 Scaffolded | `crawl_runs`/`ban_events` tables + `run_id` logging exist; population + health derivation pending M1/M4. |
| FR-11 (adversarial harness) | 🔴 Not started | M3. |
| FR-12 (price-history time-series) | 🟡 Scaffolded | `price_observations` schema exists (append-only); write/query paths pending M1. |
| FR-13 (Flask API) | 🟡 Scaffolded | App factory + `/health` only; product/history/deals routes pending M1/M4. |
| FR-14 (dashboard) | 🔴 Not started | M4. |
| FR-15 (scheduler + admin trigger) | 🔴 Not started | M4. |
| FR-16 (drift detection) | 🔴 Not started | M4. |
| FR-17 (deal detection) | 🔴 Not started | M4. |

**Legend:** ✅ done · 🟡 scaffolded/substantial (foundation or partial behavior in place, not
yet delivered end-to-end) ·
🔴 not started · ⬜ milestone not started · ⏳ next up.

## 9. Open questions (resolve as ADRs)
1. Concrete v1 sources per technique (candidate: Shopify `products.json` REST + Storefront
   GraphQL + a JS-rendered store page). Legal check per `docs/08`.
2. Proxy provider abstraction — env-configured pool vs. a single proxy; harness works
   without real proxies.
3. Scheduler: in-process (APScheduler) vs. external cron/container. See ADR.
4. Dashboard: server-rendered Jinja + Chart.js vs. a small SPA. Default: Jinja + Chart.js.

## 10. Explicit anti-requirements
- **Never** persist a response that failed validation or a data-quality gate.
- **Never** target auth-walled or PII data.
- **Never** disable `robots.txt`/rate-limit obedience globally.
- **Never** stake tests on a live hostile site — prove resilience via the harness.
- **Never** store money as a float or without a currency.
