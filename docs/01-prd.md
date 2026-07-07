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

*Snapshot as of 2026-07-08. Kept in sync with `plan/backlog.md` and the "Current status"
section of `CLAUDE.md`; those are the source of truth for task-level state.*

### Progress at a glance

**How far along: 25 / 28 backlog tasks complete (~89%); 4 of 5 milestones gated; M3 complete, M4 (intelligence + hardening) underway (3/6).**

```
Done  ████████████████████████████████████░░░░  89%   (M0 ✅  M1 ✅  M2 ✅  M3 ✅  M4 🟡)
```

| Phase | Tasks | Status | Delivers |
|-------|:-----:|--------|----------|
| **M0 — Foundation** | 6 / 6 | ✅ Gated | uv/Docker/Postgres, config boundary, Scrapy + Flask skeletons, CI, `/health` |
| **M1 — First REST slice** | 7 / 7 | ✅ Gated | one command: crawl → validate → normalize → dedup → persist → serve, with freshness |
| **M2 — More techniques** | 3 / 3 | ✅ Gated | all three kinds (REST/HTML/GraphQL) feed the identical pipeline + storage → canonical products |
| **M3 — Resilience + harness** | 6 / 6 | ✅ Gated | harness (T3.1) + ban classifier (T3.2) + throttle/backoff/circuit-breaker (T3.3) + proxy/identity rotation (T3.4) + data-quality gates (T3.5) + full-scenario integration (T3.6) — **the centerpiece**: recovery + ban ledger + zero garbage proven end-to-end vs. the harness |
| **M4 — Intelligence + hardening** | 3 / 6 | 🟡 Underway | price history + deals + `GET /deals` (T4.1) + change/selector-drift detection (T4.2) + Jinja/Chart.js dashboard (T4.3) done; /health/sources + metrics, scheduler + admin crawl, demo/CI polish next |

The foundation and the first end-to-end REST slice are done and proven; a single command crawls a
source through the full pipeline and the API serves it with freshness, and all three acquisition
techniques — a paginated **REST** extractor, a Playwright-rendered **HTML** extractor, and a
cursor-paginated **GraphQL** extractor — now land under the same contract, feeding one shared
pipeline + storage (M2 gated). Now the **anti-bot resilience layer (M3) — the largest and
highest-value phase — is COMPLETE (gate passed)**: its adversarial mock harness (the deterministic
adversary every resilience task is proven against) landed, and **all six of its tasks are done** —
the ban/anti-bot **classifier** (never cache garbage), **adaptive throttle + Retry-After backoff +
per-domain circuit breaker**, the **proxy pool + coherent identity rotation**, the **data-quality
gates** (range/continuity/volume → quarantine, never silent-store), and the **full-scenario
integration gate** (T3.6) that proves the whole stack recovers, records the ban audit trail, and
persists zero garbage end-to-end against the harness. The remaining phase, the intelligence/hardening
layer (M4), is now underway (3/6) — **price history + deals** (`GET /deals`, T4.1),
**change/selector-drift detection** (T4.2, a drifted source raises a `flagged` run), and a
**light Jinja + Chart.js dashboard** (T4.3, per-product price charts + a crawler-health panel with
ban-rate trend and identity/proxy rotations) have landed. By task count ~89%; the single biggest
chunk of work — the core competency this project exists to demonstrate — is delivered and gated.
Per-milestone, per-task, and per-FR detail follows.

**Overall: M0 (Foundation), M1 (first REST slice), and M2 (more techniques) complete and gated —
all three acquisition kinds (REST/HTML/GraphQL) now feed one pipeline; M3 (the resilience
centerpiece) is COMPLETE and gated — harness, ban classifier, throttle/backoff/circuit-breaker,
proxy/identity rotation, data-quality gates, and full-scenario integration all land, proving
recovery + ban ledger + zero garbage end-to-end.** The platform boots, migrates, and answers
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
and follows cursor pagination (T2.2) — both under the same `SourceExtractor` contract, and closed
the milestone with a **three-kinds parity gate** (T2.3): a parameterized integration test drives
all three fixture sets through the *one* shared normalize + persistence path into Postgres →
identical canonical products, backed by a structural guard that the shared layers name no concrete
source. **M2 gate passed.** **M3, the anti-bot resilience layer, is COMPLETE (gate passed):** on top
of the adversarial harness, the response **classifier** gates every download (a block/CAPTCHA/empty
page is recorded as a `BanEvent` and dropped, never stored), an **adaptive throttle +
Retry-After-aware full-jitter backoff + per-domain circuit breaker** govern rate and failure, a
**proxy pool + coherent identity rotation** recover from a persistent block by escalating from the
honest contact UA to a coherent browser bundle (fresh cookie jar), **data-quality gates**
(range/continuity per item; a run-atomic volume gate that quarantines and commits nothing on a
baseline breach) enforce FR-9's "never silent-store", and the **full-scenario integration gate**
(T3.6) proves it all end-to-end — a real crawl subprocess per harness scenario into Postgres:
`happy`/`rate_limited`/`block_after_n` recover the full catalogue, `captcha`/`soft_ban` persist zero
observations and record `ban_events` with the right kind/action, and no blocked/invalid/quarantined
response ever becomes a `price_observation`.

### Milestone progress

| Milestone | State | Notes |
|-----------|-------|-------|
| **M0 Foundation** | ✅ Complete | Gate passed: `docker compose up` + `uv run` boot; `/health` reflects DB; strict ruff/mypy/pytest green; CI wired. |
| **M1 First vertical slice (REST)** | ✅ Complete | Gate passed: `acquire-intel crawl demo_rest` → observations in Postgres → API serves them with freshness (E2E test + live curl); strict ruff/mypy/pytest green. |
| **M2 More techniques (HTML/GraphQL)** | ✅ Complete | Gate passed: REST/HTML/GraphQL all produce canonical products through one pipeline + storage (parameterized parity test + source-agnostic structural guard); strict ruff/mypy/pytest green. |
| **M3 Resilience + harness** | ✅ Complete | Gate passed: the whole resilience stack recovers from rate-limits/blocks/soft-bans, records the `ban_events` audit trail, and persists **0** blocked/invalid/quarantined rows — proven end-to-end vs. the harness (T3.1–T3.6). strict ruff/mypy/pytest green (256 passed). |
| **M4 Intelligence + hardening** | 🟡 In progress | Price history + deals (`GET /deals`, T4.1) ✅; change/selector-drift detection (T4.2) ✅; Jinja/Chart.js dashboard (T4.3) ✅ (284 passed). Next: /health/sources + metrics → scheduler + admin crawl → demo/CI polish. |

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
| T2.3 — Three-kinds parity | ✅ Done | `tests/test_three_kinds_parity.py`: a parameterized integration test (`rest`/`html`/`graphql`) parses each fixture with its own extractor → `RawProduct`s, then drives all three through the **one** shared `normalize` → `ProductRepository.upsert` / `PriceObservationRepository.append` path into Postgres → identical canonical `{source}:{external_id}` products + immutable `Decimal`-money observations. Plus a structural guard that the shared pipeline/storage modules import nothing from `acquisition.sources` and name no concrete source. **M2 gate passed** (146 passed / 0 skipped, DB up). |

### M3 progress (resilience — the centerpiece)

| Task | State | Notes |
|------|-------|-------|
| T3.1 — Adversarial mock harness | ✅ Done | `harness/` (new top-level dev/test package, not in the wheel): a self-contained Flask mock server (ADR-0009) selecting scenarios by path — `happy`, `rate_limited` (429+Retry-After burst → 200), `block_after_n` (403 past a per-identity budget; fresh identity resets it), `captcha` (200 challenge page), `cookie_wall` (403+Set-Cookie until the cookie is carried), `soft_ban` (200+empty), `drift` (renamed item fields). Deterministic: count-based scenarios key on identity (`X-Harness-Identity`→`User-Agent`→addr) and `POST /__admin__/reset` clears state. `uv run python -m harness.server` (see `harness/README.md`). 12 self-tests + verified live via curl; `mypy src harness` + pytest `pythonpath` wired. |
| T3.2 — Ban / anti-bot classifier | ✅ Done | `resilience/classifier.py` (pure `classify(status, body)` → `ok/rate_limited/blocked/captcha/empty`: CAPTCHA markers win over status; 429→rate_limited; other non-2xx→blocked; 2xx empty body→empty, but a non-empty empty-array→ok) + `resilience/middleware.py` (`BanDetectionMiddleware` @585): `ok` passes through, a ban is recorded (stats `acquire/ban_events`+`acquire/ban/{kind}`, log, `BanEvent` on the spider sink) and **dropped via `IgnoreRequest`** so it never reaches an extractor; robots.txt never gated. 19 classifier tests (incl. all 7 harness scenarios) + 6 middleware tests; verified in the real engine (captcha→0 items/1 ban, happy→3 items/0 bans). |
| T3.3 — Throttle, backoff, circuit-breaker | ✅ Done | AutoThrottle + per-domain caps from config; `resilience/backoff.py` (pure full-jitter exponential honouring `Retry-After`) + `BackoffRetryMiddleware` @585 retries 429/503 with a real `await asyncio.sleep`, bounded (then falls through to the ban gate); `resilience/circuit.py` (pure per-domain state machine) + `CircuitBreakerMiddleware` @583 trips on repeated `blocked/captcha/empty` and short-circuits an open domain, with a half-open probe after cool-down. 43 tests (backoff maths, circuit FSM, both middlewares incl. the real harness rate-limit sequence) + verified in the real engine (rate_limited → 3 items, 2 retries, 0 bans). |
| T3.4 — Proxy manager + identity rotation | ✅ Done | `resilience/proxy.py` (`ProxyPool`: pure, clock-injectable round-robin over healthy proxies, per-proxy tallies, banned → quarantine cool-down, **zero-proxy = direct** and all-cooling-down degrades to direct; env-supplied, never hardcoded) + `resilience/identity.py` (`BrowserProfile`/`IdentityPool`: **coherent** bundles — UA + matching client-hints/headers/viewport/locale — rotated whole with a fresh per-identity cookie jar). `IdentityRotationMiddleware` @582 is **respectful by default** (honest contact UA until a block), then **escalates** to a browser identity + fresh proxy on a persistent block (resets the harness's per-identity budget), retries a `Set-Cookie` cookie wall with the *same* identity (replays the session cookie), and never rotates on rate-limits (backoff owns those); bounded per request, then falls to the ban gate. 18 tests incl. real-harness `block_after_n` + `cookie_wall`. ADR-0011. |
| T3.5 — Data-quality gates | ✅ Done | `pipeline/quality.py` (pure `check_range`/`check_continuity`/`check_volume` + `GateThresholds` + `QualityIssue`). **Per-item** gates in `QualityGatePipeline` @350 drop out-of-range / discontinuous items (counted, never persisted); the **run-level volume** gate makes `PersistencePipeline` run-atomic — it buffers survivors and at close compares the count to the source's committed baseline (`CrawlRunRepository.baseline_count`), flushing all within tolerance or **committing nothing** on a breach (append-only store has no delete, ADR-0012). A quarantined run is a first-class ledger status (`RunStatus += quarantined`, no migration; runner maps the stat → `items_ok=0`). 20 tests incl. a real-Postgres proof that a volume-anomalous run stores **zero** rows and is flagged `quarantined`. ADR-0012. |
| T3.6 — Resilience integration | ✅ Done | The M3 gate. New `BanEventRepository` persists the run's `BanEvent`s to `ban_events`; the runner passes a shared sink to the spider (filled by `BanDetectionMiddleware`, no middleware→storage coupling) and records rows + count on the ledger. `test_resilience_integration.py` runs a real `acquire-intel crawl` subprocess per harness scenario into Postgres: `happy`/`rate_limited`/`block_after_n` recover the full catalogue; `captcha`/`soft_ban` persist **0** observations + a correctly-kinded/actioned `ban_events` row; every ban scenario proves **0** blocked/invalid rows persisted. 256 passed. |

### M4 progress (intelligence + hardening)

| Task | State | Notes |
|------|-------|-------|
| T4.1 — Price history + deals | ✅ Done | `analytics/deals.py` (pure `compute_deal`/`rank_deals` over `PricePoint`s): a **deal** = a product whose latest price is ≥ `deal_min_drop_pct` (default 10%) below its **recent high** (max in a `deal_window_days`, default 90, window of the product's *own* history) — never cross-product. `GET /deals` ranks by drop magnitude (ties by `product_id` → deterministic), `limit` 1–50/default 20, optional `source`; each deal carries `previousPrice`/`currentPrice`/`dropPct`/`since` under the shared freshness envelope. New `PriceObservationRepository.history_since` + `ProductRepository.get_many`; `DealOut`/`DealsResponse` serializers; `deals_bp` on the API base path. 12 tests (9 pure boundary + 3 Flask-client vs. Postgres). **New: ADR-0013**. |
| T4.2 — Change / selector-drift detection | ✅ Done | Extractors record `entries_seen`/`entries_mapped` per page (`acquisition/telemetry.py`); the runner runs the pure `analytics/drift.py::assess_drift` and ledgers a **field-drift** run (envelope intact but items unmappable — renamed fields) as a new terminal status `flagged` + a `crawl.drift_detected` alert; **container drift** (nothing even seen) stays covered by the T3.5 volume gate. Precedence: failed > flagged > quarantined > partial > success. Proven end-to-end: a real crawl of the harness `drift` scenario → 0 observations + `status=flagged`, plus pure boundary tests. **New: ADR-0014**. |
| T4.3 — Dashboard | ✅ Done | Light server-rendered **Jinja + Chart.js** dashboard over the read layer (ADR-0007), mounted at the site root (JSON API stays under `API_BASE_PATH`). `GET /` renders a **crawler-health panel** (per source: last run status, freshness vs. `stale_after`, items ok/rejected, ban count, identity/proxy **rotations**, a ban-events **sparkline**) + the collected-products table with empty states; `GET /products/<id>` renders a price chart fed **client-side** from `/products/{id}/price-history` (no duplicate serialization) with a window selector + loading/empty states; unknown id → a 404 HTML page. Thin routes: health assembly is the pure `analytics/health.py::summarize_source` (freshness rule, rotation tally, oldest→newest trend), unit-testable without a DB; new `CrawlRunRepository.recent` + `BanEventRepository.counts_by_action`. Chart.js 4.4.3 **vendored** (offline demo); theme-aware CSS. 9 tests (5 pure + 4 Flask view); 284 passed / 0 skipped. Verified live vs. the harness. |
| T4.4 — /health/sources + metrics | ⬜ Todo | Per-source health, freshness, ban-rate, proxy-health (docs/07). |
| T4.5 — Scheduler + admin crawl | ⬜ Todo | Scheduled collection + `POST /admin/crawl`. |
| T4.6 — Demo & CI/CD polish | ⬜ Todo | End-to-end demo + CI/CD hardening. |

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
| FR-5 (resilience layer) | ✅ Done | M3 centerpiece, fully delivered across T3.3–T3.4. **Throttle/backoff/circuit-breaking** (T3.3): AutoThrottle + per-domain caps; Retry-After-aware full-jitter backoff retrying 429/503 (bounded); per-domain breaker that trips on repeated blocks and cools down. **Proxy pool + coherent identity/fingerprint rotation** (T3.4): a health-tracking `ProxyPool` (quarantine cool-down, zero-proxy = direct) + an `IdentityPool` of coherent UA/header/client-hint/cookie/viewport bundles, escalating from the honest contact UA to a fresh browser identity + proxy on a persistent block. Proven against the harness (`rate_limited`/`block_after_n`/`cookie_wall`) + in the real engine. |
| FR-6 (ban detection) | ✅ Done | **Detection + gating** (T3.2): `classify` labels every response `ok/rate_limited/blocked/captcha/empty` (status + body markers + empty-body) and `BanDetectionMiddleware` records a `BanEvent` and drops any ban via `IgnoreRequest` — a block/CAPTCHA/empty page is never stored. **Reaction** now closes the loop: rate-limits back off (T3.3), and a persistent block **rotates identity/proxy and retries** (T3.4) instead of just dropping. Proven against all 7 harness scenarios + in the real engine. |
| FR-7 (boundary validation) | ✅ Done | Config + extractor output validated via `RawProduct` (`extra="forbid"`, T1.1); the pipeline re-asserts the boundary and rejects+counts unmappable items, never persisting garbage (T1.4) — now exercised in a live crawl (T1.7). Deeper data-quality gates (range/continuity/volume) now land in FR-9/T3.5. |
| FR-8 (normalize + dedup pipeline) | ✅ Done | Scrapy item pipeline normalizes `RawProduct` → `Product` + `PriceObservation` (Decimal money, canonical id, currency fallback) and dedups within a run, rejecting/counting invalid (T1.2/T1.4, ADR-0010); its output is persisted by `PersistencePipeline` and proven end-to-end (T1.7). |
| FR-9 (data-quality gates) | ✅ Done | T3.5 (ADR-0012): shape (upstream `RawProduct`/`normalize`) + **range** (plausible price band) + **continuity** (per-product jump vs. last committed price) drop bad items inline (counted, never persisted), and a run-atomic **volume** gate quarantines a whole run — committing **nothing** — when its surviving count strays from the source baseline, recorded as `crawl_runs.status="quarantined"`. Proven by unit + real-Postgres integration tests (a volume-anomalous run stores zero rows). |
| FR-10 (crawl-run ledger) | ✅ Done | The runner opens a `crawl_runs` row before the crawl and closes it with a terminal status (`success`/`partial`/`failed`/`quarantined`) + `items_ok`/`items_rejected` from Scrapy stats, even on crash (T1.5/T1.7/T3.5). **Ban-event recording now lands** (T3.6): a `BanEventRepository` persists each run's detected bans to `ban_events` with the count on the ledger row. **Health/freshness derivation over the ledger is now surfaced** by the T4.3 dashboard's crawler-health panel (last run status, freshness vs. `stale_after`, items ok/rejected, ban count, identity/proxy rotations, ban-events trend); the formal per-source health classification + `/health/sources` + metrics catalog is T4.4. |
| FR-11 (adversarial harness) | ✅ Done | `harness/` (T3.1, ADR-0009): a self-contained Flask mock server with path-selected, deterministic scenarios — `happy`/`rate_limited`/`block_after_n`/`captcha`/`cookie_wall`/`soft_ban`/`drift` — keyed per-identity with a `__admin__/reset` control. 12 self-tests + verified live; `uv run python -m harness.server`. The resilience tasks (T3.2–T3.6) are proven against it. |
| FR-12 (price-history time-series) | ✅ Done | Append-only `price_observations` is populated by a live crawl (T1.7), proven immutable across re-runs (T1.5), and served over HTTP as `GET /products/{id}/price-history` with freshness + windowing (T1.6) — the full capture→serve path is exercised end-to-end. |
| FR-13 (Flask API) | 🟡 Substantial | App factory + `/health` (M0) plus read routes `GET /products`, `GET /products/{id}/price-history` (T1.6), and now `GET /deals` (T4.1) — spec-conformant camelCase, freshness envelope, 404 problem+json, response shapes validated vs pydantic models. `/admin/crawl` + `/health/sources` routes pending M4. |
| FR-14 (dashboard) | ✅ Done | T4.3 (ADR-0007): a light server-rendered **Jinja + Chart.js** dashboard at the site root — `GET /` shows a **crawler-health panel** (per source: last run status, freshness, items ok/rejected, ban count, identity/proxy rotations, ban-events sparkline) + the collected-products table (empty states included), and `GET /products/<id>` shows a per-product **price chart** fed client-side from the price-history JSON (window selector, loading/empty states; unknown id → 404 page). Health assembly is pure (`analytics/health.py`), Chart.js is vendored (offline), CSS is theme-aware; 9 tests + verified live vs. the harness. The full healthy/degraded/stale/failing classifier + metrics catalog is T4.4. |
| FR-15 (scheduler + admin trigger) | 🔴 Not started | M4. |
| FR-16 (drift detection) | ✅ Done | T4.2 (ADR-0014): a source whose output *shape* shifted (renamed fields → items seen but unmappable) raises a `flagged` run, not a silent near-empty crawl; **container drift** (nothing seen) is caught by the T3.5 volume gate. `assess_drift` is pure; proven by a real harness-`drift` crawl (→ `status=flagged`) + unit tests. Alert, don't crash. |
| FR-17 (deal detection) | ✅ Done | T4.1 (ADR-0013): a **deal** = a product whose latest price is ≥ `deal_min_drop_pct` below its recent high (max in a `deal_window_days` window of its *own* history), served at `GET /deals` ranked by drop magnitude with `source`/`limit` filters + freshness. Pure, deterministic math (`analytics/deals.py`) proven by unit + Flask-client integration tests. |

**Legend:** ✅ done · 🟡 scaffolded/substantial (foundation or partial behavior in place, not
yet delivered end-to-end) ·
🔴 not started · ⬜ milestone not started · ⏳ next up.

## 9. Open questions (resolve as ADRs)
1. Concrete v1 sources per technique (candidate: Shopify `products.json` REST + Storefront
   GraphQL + a JS-rendered store page). Legal check per `docs/08`.
2. ~~Proxy provider abstraction — env-configured pool vs. a single proxy; harness works
   without real proxies.~~ **Resolved (ADR-0011):** an env-configured `PROXY_URLS` pool with
   per-proxy health/quarantine; an empty pool = direct connection, so the harness needs no real
   proxies.
3. Scheduler: in-process (APScheduler) vs. external cron/container. See ADR.
4. ~~Dashboard: server-rendered Jinja + Chart.js vs. a small SPA. Default: Jinja + Chart.js.~~
   **Resolved (ADR-0007, delivered in T4.3):** server-rendered Jinja + Chart.js (Chart.js
   vendored for an offline demo), mounted at the site root over the read layer.

## 10. Explicit anti-requirements
- **Never** persist a response that failed validation or a data-quality gate.
- **Never** target auth-walled or PII data.
- **Never** disable `robots.txt`/rate-limit obedience globally.
- **Never** stake tests on a live hostile site — prove resilience via the harness.
- **Never** store money as a float or without a currency.
