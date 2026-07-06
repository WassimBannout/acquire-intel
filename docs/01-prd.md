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

### Progress at a glance

**How far along: 15 / 28 backlog tasks complete (~54%); 2 of 5 milestones gated, M2 underway.**

```
Done  █████████████████████░░░░░░░░░░░░░░░░░░░  54%   (M0 ✅  M1 ✅  M2 🟡  M3 ⬜  M4 ⬜)
```

| Phase | Tasks | Status | Delivers |
|-------|:-----:|--------|----------|
| **M0 — Foundation** | 6 / 6 | ✅ Gated | uv/Docker/Postgres, config boundary, Scrapy + Flask skeletons, CI, `/health` |
| **M1 — First REST slice** | 7 / 7 | ✅ Gated | one command: crawl → validate → normalize → dedup → persist → serve, with freshness |
| **M2 — More techniques** | 2 / 3 | 🟡 Underway | HTML (Playwright, T2.1) + GraphQL (T2.2) extractors done; three-kinds parity (T2.3) next — the M2 gate |
| **M3 — Resilience + harness** | 0 / 6 | ⬜ Not started | proxy/identity rotation, throttle/backoff, ban detection, adversarial harness — **the centerpiece** |
| **M4 — Intelligence + hardening** | 0 / 6 | ⬜ Not started | deals/drift detection, dashboard, scheduler + admin crawl, metrics, demo/CI polish |

The foundation and the first end-to-end REST slice are done and proven; a single command crawls a
source through the full pipeline and the API serves it with freshness, and the second and third
techniques — a Playwright-rendered **HTML** extractor and a **GraphQL** extractor — now land under
the same contract (M2 underway). What remains is the three-kinds parity check (the M2 gate), the
**anti-bot resilience layer (M3) — the largest and highest-value phase**, and the
intelligence/hardening layer (M4). By task count ~54%;
**effort-weighted it is nearer the midpoint**, since M3 alone is the single biggest chunk of the
remaining work and the core competency this project exists to demonstrate. Per-milestone,
per-task, and per-FR detail follows.

**Overall: M0 (Foundation) and M1 (first REST slice) complete and gated; M2 (more techniques)
underway — the HTML (Playwright) and GraphQL extractors now land.** The platform boots, migrates, and answers
`/health`; the canonical data contracts exist and are parity-tested; and a single command,
`acquire-intel crawl demo_rest`, drives the **whole slice**: the REST extractor fetches a
paginated `products.json` → the Scrapy item pipeline validates → normalizes (Decimal money,
canonical id, UTC capture) → dedups (rejecting/counting anything unmappable) → the persistence
pipeline upserts the `products` projection and appends immutable `price_observations`, with the
runner opening/closing a `crawl_runs` ledger row (terminal status + item counts) around it → the
**read API serves that data over HTTP** — `GET /products` and `GET /products/{id}/price-history`,
each carrying freshness (`dataAsOf` + `stale`) and per-point `capturedAt`/`sourceId`, with
`Money.amount` as a string and a 404 problem+json for unknown products. The whole path is proven
by an end-to-end test (a real CLI subprocess crawling a local fixture server → Postgres → API)
plus focused integration tests, all against Postgres. **M2 has since added the second and third
techniques** — `demo_html`, a JS-rendered **HTML** source that `scrapy-playwright` renders and
parses (T2.1), and `demo_graphql`, a **GraphQL** source that issues a typed query as a JSON `POST`
and follows cursor pagination (T2.2) — both under the same `SourceExtractor` contract. What's next
in M2: the three-kinds parity check (T2.3, the M2 gate) proving all three feed the identical
pipeline/storage.

### Milestone progress

| Milestone | State | Notes |
|-----------|-------|-------|
| **M0 Foundation** | ✅ Complete | Gate passed: `docker compose up` + `uv run` boot; `/health` reflects DB; strict ruff/mypy/pytest green; CI wired. |
| **M1 First vertical slice (REST)** | ✅ Complete | Gate passed: `acquire-intel crawl demo_rest` → observations in Postgres → API serves them with freshness (E2E test + live curl); strict ruff/mypy/pytest green. |
| **M2 More techniques (HTML/GraphQL)** | 🟡 In progress | T2.1 HTML (Playwright) ✅ + T2.2 GraphQL ✅ done. Next: T2.3 three-kinds parity (M2 gate). |
| **M3 Resilience + harness** | ⬜ Not started | The centerpiece; unbuilt. |
| **M4 Intelligence + hardening** | ⬜ Not started | — |

### M1 progress (REST slice)

| Task | State | Notes |
|------|-------|-------|
| T1.1 — SourceExtractor contract + RawProduct | ✅ Done | `acquisition/extractor.py`: `RawProduct` pydantic model (`extra="forbid"`) + `runtime_checkable` `SourceExtractor` Protocol; parity-tested vs `raw-product.schema.json`. |
| T1.2 — Canonical models + contract parity | ✅ Done | `contracts.py`: `Money`(Decimal+currency, string-serialized), `Product`, `PriceObservation`, `CrawlRun`, `BanEvent`; UTC-normalizing datetime; parity + money/UTC/enum invariant tests green. |
| T1.3 — REST extractor | ✅ Done | `sources/demo_rest.py`: `DemoRestExtractor` (`kind="rest"`) walks a paginated Shopify-style `products.json` → `RawProduct`s; malformed/blocked page → nothing; fixtures + 12 tests green. |
| T1.4 — Pipeline: validate → normalize → dedup | ✅ Done | `pipeline/normalize.py` + `NormalizePipeline`: `RawProduct` → `Product` + `PriceObservation` (Decimal money, canonical id, currency fallback, UTC capture); in-run dedup keep-first; invalid rejected + counted. ADR-0010. |
| T1.5 — Persistence + crawl-run ledger | ✅ Done | `storage/repositories.py`: `products` upsert (ON CONFLICT, preserve `first_seen_at`), append-only `price_observations`, `crawl_runs` open/close. Postgres integration test proves re-run appends + upserts + records the run. |
| T1.6 — GET /products + /price-history | ✅ Done | `api/products.py` + camelCase `api/serializers.py`: both routes per `specs/openapi.yaml` with `dataAsOf`+`stale` freshness, per-point `capturedAt`/`sourceId`, `Money.amount` as string, `latestPrice`/`inStock` derived from newest observation (`DISTINCT ON`), `window` filter, 404 problem+json; 9 Flask test-client tests, verified live via curl. |
| T1.7 — End-to-end REST slice | ✅ Done | `pipeline/persistence.py` (`PersistencePipeline` @400) + `acquisition/runner.py` crawl-run ledger: `acquire-intel crawl demo_rest` reads source config from the `sources` registry, opens/closes a `crawl_runs` row (status + counts, even on crash), persists products + observations, and the API serves them with freshness. E2E test (real CLI subprocess → fixture server → Postgres → API) + live curl. **M1 gate passed.** |

### M2 progress (more techniques)

| Task | State | Notes |
|------|-------|-------|
| T2.1 — HTML extractor (Playwright) | ✅ Done | `sources/demo_html.py`: `DemoHtmlExtractor` (`kind="html"`) renders a JS-built listing via `scrapy-playwright` (waits for `[data-product-id]`) and maps rendered HTML → `RawProduct`s with a pure, browser-independent parser over resilient `data-*` selectors; missing price/id → skipped, selector drift → yields nothing. `scrapy-playwright` added (ADR-0002); Playwright handlers wired globally-but-lazily so REST is unaffected. 12 tests incl. a real Chromium render smoke test; fixtures under `tests/fixtures/demo_html/`. |
| T2.2 — GraphQL extractor | ✅ Done | `sources/demo_graphql.py`: `DemoGraphqlExtractor` (`kind="graphql"`) issues a typed `Products($first,$after)` operation as a JSON `POST` (`JsonRequest`) against a Storefront-style Relay connection and follows **cursor pagination** (`pageInfo.endCursor` in the next request's variables); nodes → `RawProduct`s (per-node `currencyCode` carried through); a GraphQL `errors`/block/wrong-shape response → nothing (stops paging), a null-price node → skipped. Query derived from public Storefront docs (documented in-module, ADR-0004). 13 tests; fixtures under `tests/fixtures/demo_graphql/`. |
| T2.3 — Three-kinds parity | ⬜ Todo | One parameterized test: REST/HTML/GraphQL fixtures → canonical products through the identical pipeline. M2 gate. |

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
| FR-1 (Scrapy engine) | 🟡 Substantial | Scrapy drives a real one-shot crawl end-to-end (scheduler, downloader, item pipelines, pagination); per-source config (`base_url`/currency) comes from the `sources` registry and the crawl-run ledger is opened/closed around it (T1.7). Shared resilience middlewares (throttle/backoff/rotation) are M3. |
| FR-2 (REST extractor) | ✅ Done (REST) | `demo_rest` (`kind="rest"`, T1.3) walks a paginated Shopify-style `products.json` → `RawProduct`s and is now wired through the full pipeline → persistence → API, proven by the E2E gate against a fixture server (T1.7). Additional real REST sources are additive on the same contract. |
| FR-3 (HTML/Playwright) | ✅ Done | `demo_html` (`kind="html"`, T2.1) renders a JS-built page via `scrapy-playwright` (waits for the grid) and maps rendered HTML → `RawProduct`s with resilient `data-*` selectors; selector drift → yields nothing. Fixture-tested browser-free + a real Chromium render smoke test. Additional HTML sources are additive on the same contract. |
| FR-4 (GraphQL extractor) | ✅ Done | `demo_graphql` (`kind="graphql"`, T2.2) builds a typed `Products($first,$after)` query, POSTs it as JSON (`JsonRequest`), and follows cursor pagination via `pageInfo.endCursor`; nodes → `RawProduct`s with per-node currency; malformed/`errors`/wrong-shape → nothing. Fixture-tested (valid → expected, cursor follow/stop, 4× rejection). |
| FR-5 (resilience layer) | 🔴 Not started | M3 centerpiece. |
| FR-6 (ban detection) | 🔴 Not started | M3. |
| FR-7 (boundary validation) | ✅ Done | Config + extractor output validated via `RawProduct` (`extra="forbid"`, T1.1); the pipeline re-asserts the boundary and rejects+counts unmappable items, never persisting garbage (T1.4) — now exercised in a live crawl (T1.7). Deeper data-quality gates (volume/range/continuity) are FR-9/M3. |
| FR-8 (normalize + dedup pipeline) | ✅ Done | Scrapy item pipeline normalizes `RawProduct` → `Product` + `PriceObservation` (Decimal money, canonical id, currency fallback) and dedups within a run, rejecting/counting invalid (T1.2/T1.4, ADR-0010); its output is persisted by `PersistencePipeline` and proven end-to-end (T1.7). |
| FR-9 (data-quality gates) | 🔴 Not started | M3. |
| FR-10 (crawl-run ledger) | ✅ Done | The runner opens a `crawl_runs` row before the crawl and closes it with a terminal status (`success`/`partial`/`failed`) + `items_ok`/`items_rejected` from Scrapy stats, even on crash (T1.5/T1.7). Ban-event recording and health/freshness derivation over the ledger are M3/M4. |
| FR-11 (adversarial harness) | 🔴 Not started | M3. |
| FR-12 (price-history time-series) | ✅ Done | Append-only `price_observations` is populated by a live crawl (T1.7), proven immutable across re-runs (T1.5), and served over HTTP as `GET /products/{id}/price-history` with freshness + windowing (T1.6) — the full capture→serve path is exercised end-to-end. |
| FR-13 (Flask API) | 🟡 Substantial | App factory + `/health` (M0) plus the two read routes `GET /products` and `GET /products/{id}/price-history` (T1.6) — spec-conformant camelCase, freshness envelope, 404 problem+json, response shapes validated vs pydantic models. `/deals`, `/admin/crawl`, `/health/sources` routes pending M4. |
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
