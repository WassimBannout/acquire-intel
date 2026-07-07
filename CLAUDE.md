# CLAUDE.md — AcquireIntel

Loaded into context at the start of every Claude Code session in this repository. It is the
standing brief. Read it fully before acting.

---

## What this project is

**AcquireIntel** is a **resilient, pluggable data-acquisition platform** in **Python**. Its
flagship dataset is **product & price intelligence**: it crawls online stores and extracts
product/price data via three techniques — **HTML scraping (Scrapy + Playwright)**, **REST**
APIs, and **GraphQL** APIs — persists an append-only **price-history time-series**, and
serves it through a **Flask** API + light dashboard.

The engineering centerpiece is the **acquisition engine and its anti-bot resilience
layer** (proxy rotation, fingerprint/header/cookie rotation, adaptive throttling,
backoff/retry, ban detection, session pools). Correctness of that layer is proven against a
**local adversarial mock server** (`docs/06`, ADR-0009) so it is deterministically testable
by the agent itself.

This project exists to demonstrate, in one coherent codebase, the competencies of a **Data
Acquisition / Research Engineer**: Python; Scrapy/Playwright; REST + GraphQL; adversarial
data collection (rate limits, blocking, anti-bot); networking fundamentals (proxies,
headers, cookies); scalable pipelines; data-quality monitoring; CI/CD.

## Working agreement (how we build here)

1. **Spec-first, always.** Behavior change → update the doc/spec under `docs/` or `specs/`
   **before** writing code. Code conforms to spec, never the reverse.
2. **Vertical slices.** Ship the thinnest end-to-end increment (discover → fetch → parse →
   validate → persist → serve) for one source, not horizontal layers in isolation.
3. **Definition of done = acceptance criteria met + tests green (incl. adversarial harness)
   + verified running.** See `docs/06`. "It runs once" is not done.
4. **No secrets in code or git.** Credentials/proxies via env only. `.env` is git-ignored;
   ship `.env.example` with keys, no values.
5. **Legal & respectful acquisition.** Public data only; honor `robots.txt` and rate limits
   by default; identify a contact User-Agent; document any exception. See `docs/08`.
   Anti-bot techniques exist for **reliability on public data**, not to defeat auth/PII
   walls.
6. **Every non-obvious decision becomes an ADR** (`docs/adr/`, use the template).
7. **Small, reviewable changes.** One backlog task at a time; reference the task id in
   commits.

## Architecture at a glance

- **Single Python package**, `src/` layout, managed with **uv** + `pyproject.toml`.
- **Scrapy** is the crawl backbone (scheduler, concurrency, downloader middlewares, item
  pipelines). **Playwright** (via `scrapy-playwright`) renders JS-heavy pages. See ADR-0002.
- **Source extractors are pluggable** behind a `SourceExtractor` protocol — one per source,
  of kind `html` | `rest` | `graphql`. Adding a source = one module + registration
  (ADR-0003, `specs/extractor-interface.md`).
- **Resilience layer** (the anti-bot star): proxy manager, identity/fingerprint rotation,
  adaptive throttle, backoff/retry, ban detection — implemented as Scrapy middlewares +
  a `resilience` module (ADR-0005, `docs/04`).
- **Pipeline:** pydantic validation → normalization → dedup → data-quality gates → persist.
- **Storage:** **PostgreSQL** via SQLAlchemy 2.0. Append-only `price_observations`
  time-series + `products` projection + `crawl_runs` health ledger (ADR-0006, `docs/03`).
- **API:** **Flask** + pydantic serialization; light dashboard (ADR-0007).
- **Adversarial harness:** a controllable mock server simulating 429/403/CAPTCHA/cookie
  walls/rate limits, used to test the resilience layer deterministically (ADR-0009).

Full detail: `docs/02-architecture.md` and `docs/04-acquisition-and-antibot.md`. Do not
invent an architecture that contradicts the ADRs — supersede an ADR rather than drift.

## Repository conventions

- **Layout:** `src/acquire_intel/{acquisition,resilience,pipeline,storage,analytics,api,
  monitoring,config}`, `tests/`, `harness/` (adversarial mock), `docker/`.
- **Naming:** modules `snake_case.py`; classes `PascalCase`; funcs/vars `snake_case`; env
  vars `SCREAMING_SNAKE_CASE`.
- **Validation:** every external payload (HTTP response, env, extractor output) is parsed
  through a **pydantic** model at the boundary. Never trust upstream shape.
- **Typing:** full type hints; `mypy` clean. **Ruff** for lint + format.
- **Errors:** typed exceptions; the API maps them to problem+json. Never leak internals to
  clients; full context to logs.
- **Time:** store all timestamps as timezone-aware UTC. Price observations are stamped at
  capture time.
- **Money:** prices are `Decimal` + ISO-4217 `currency`, never a bare float.

## Commands (created during Phase 0 — keep this in sync)

```bash
uv sync                              # install deps into the venv
uv run scrapy crawl <spider>         # run one spider
uv run acquire-intel crawl <source>  # CLI wrapper (on-demand crawl)
uv run flask --app acquire_intel.api run   # API + dashboard
uv run pytest                        # unit + integration + harness tests
uv run ruff check . && uv run mypy src harness   # lint + typecheck
docker compose up -d                 # Postgres for local dev (DB_HOST_PORT overrides host port)
uv run alembic upgrade head          # apply DB migrations
uv run python -m harness.server      # start the adversarial mock server
```

## Guardrails / do-not

- Do **not** commit `.env`, proxy credentials, or API keys.
- Do **not** target login-walled or PII-bearing data. Public catalog/price data only.
- Do **not** disable `robots.txt`/rate-limit obedience globally; exceptions are per-source
  and documented in `docs/08`.
- Do **not** persist a response that failed validation or a data-quality gate (never cache
  a block/CAPTCHA page as data). Fail the run and record it.
- Do **not** hardcode targets, proxies, or DB URLs — everything via `config` + env.
- Do **not** stake tests on a live hostile site; prove resilience against the local
  adversarial harness (deterministic) plus friendly real endpoints.

## Where to look

| Need | File |
|------|------|
| Why we're building this | `docs/00-vision.md` |
| Exact requirements | `docs/01-prd.md` |
| System design & diagrams | `docs/02-architecture.md` |
| Data model & time-series | `docs/03-data-model.md` |
| **Acquisition + anti-bot design** | `docs/04-acquisition-and-antibot.md` |
| Extractor contract | `specs/extractor-interface.md` |
| API contract | `specs/openapi.yaml` |
| What to build next | `plan/backlog.md` + `plan/execution-playbook.md` |
| How to prompt for it | `prompts/` |
| Decision history | `docs/adr/` |

## Current status

**Phase 0/1/2/3 complete and merged to `main` (Phase 3 (M3) — the resilience centerpiece — gate
passed, merged via PR #5, T3.1–T3.6 ✅); Phase 4 (M4) — intelligence + hardening — in progress:
price history + deals (T4.1 ✅) lands; change/drift detection (T4.2) next.** All three acquisition
kinds (REST/HTML/GraphQL) feed one pipeline, and the
first REST vertical slice runs end to end (crawl → pipeline → Postgres → API with freshness). The
app is built
**nested in this repo** (not a sibling `../acquire-intel-app`) — one coherent codebase, per the
vision. App scaffold lives at the repo root: `pyproject.toml` (uv), `src/acquire_intel/` with
the eight concern-modules, `tests/`. Python 3.12 pinned via `.python-version`.

- **T0.1 — Scaffold uv project ✅** (`uv sync`, ruff, mypy strict, `acquire-intel` CLI stub,
  CLI smoke tests all green).
- **T0.2 — Config & env boundary ✅** — `config/` is the single env boundary
  (`get_settings()`, pydantic-settings, `lru_cache`, fail-fast `ConfigError`); `.env.example`
  ships every key; no `os.environ` outside `config/`. `pydantic-settings` is the first runtime
  dep (ADR-0008).
- **T0.3 — Postgres + Docker + storage baseline ✅** — `docker-compose.yml` (Postgres 16;
  host port via `DB_HOST_PORT`, default 5432); SQLAlchemy 2.0 models for
  `sources/products/price_observations/crawl_runs/ban_events` (+ indexes per docs/03 §4);
  Alembic baseline migration (autogenerated, `alembic check` clean); `storage/db.py`
  engine/session; `SourceRepository` smoke test round-trips against the compose DB.
- **T0.4 — Scrapy skeleton + CLI ✅** — Scrapy embedded in `acquisition/` (settings from
  config, no-op spider, source-registry stub); `acquire-intel crawl <source>` runs a one-shot
  crawl; structlog JSON logging (`monitoring/logging.py`) routes our events *and* Scrapy's
  stdlib logs through one stream, each carrying `run_id`. `scrapy` + `structlog` added.
- **T0.5 — Flask skeleton + health ✅** — Flask app factory (`create_app`, base path from
  config); RFC 9457 `application/problem+json` handlers (app/HTTP/uncaught, internals never
  leaked); `GET /api/v1/health` returns 200 when Postgres reachable, 503 otherwise. `flask`
  added. Verified live with curl (200 up / 503 down / 404 problem+json).
- **T0.6 — CI pipeline ✅** — `.github/workflows/ci.yml`: on PR/main push, `uv sync --locked`
  → ruff check → ruff format --check → mypy → alembic upgrade → pytest, with a Postgres 16
  service container. Verified locally against the full command sequence (19 passed).

**Phase 0 gate: DONE.** `docker compose up` + `uv run` boot; `/health` reflects DB; strict
ruff/mypy/pytest all green; CI wired.

### Phase 1 — First vertical slice: REST (M1)

- **T1.1 — SourceExtractor contract + RawProduct ✅** — `acquisition/extractor.py` defines the
  `RawProduct` pydantic model (required `external_id`/`title`(min-len 1)/`url`/`raw_price`
  string|number; nullable `currency`/`in_stock`/`brand`/`image_url`; open `extra`;
  `extra="forbid"` so junk/block payloads can't construct — ADR-0008) and the
  `runtime_checkable` `SourceExtractor` Protocol (`id`, `kind: html|rest|graphql`,
  `stale_after`, `start_requests`, `parse`). Parity test asserts the model never diverges from
  `specs/data-contracts/raw-product.schema.json`; valid-accepted / invalid-rejected +
  protocol-conformance tests green (18 new, full suite 34 passed / 3 Postgres-skipped). No new
  ADR (contract already set by ADR-0003/0008).

- **T1.2 — Canonical models + contract parity ✅** — `contracts.py` (top-level) defines the
  canonical pydantic models: `Money` (Decimal + ISO-4217 currency, serialized as a **string**,
  never a float), `Product` (projection with optional nested `Money`), `PriceObservation`
  (append-only, flat amount+currency), `CrawlRun` (status enum, item counts, array of typed
  `BanEvent`s, timings), `BanEvent` (kind/action enums). Shared `UtcDatetime` type rejects
  naive datetimes and normalizes to UTC. Parity tests assert every model matches its
  `specs/data-contracts/` JSON Schema (property/required/closed/serialized-types/date-time
  formats via a validation-vs-serialization schema comparison); money/UTC/enum invariant tests
  green (24 new, full suite 58 passed / 3 Postgres-skipped). No new ADR (contract already set by
  ADR-0008/docs/03).

- **T1.3 — REST extractor ✅** — `acquisition/sources/demo_rest.py` defines `DemoRestExtractor`,
  the first concrete `SourceExtractor` (`kind="rest"`): a `scrapy.Spider` subclass (following the
  `NoOpSpider` registry precedent) that also satisfies the protocol, with `async start()`
  bridging to `start_requests()`. Fetches a paginated Shopify-style `products.json`
  (`?page=N` until an empty page), maps each product → `RawProduct`, and **never emits garbage**:
  a malformed/blocked/non-JSON/wrong-shape page yields nothing (and stops paging), and any item
  missing a required field (e.g. no price) is skipped, not fabricated (ADR-0008). Registered as
  `demo_rest`. Fixtures under `tests/fixtures/demo_rest/` (valid payload w/ one bad item +
  expected output + malformed); 12 fixture tests green (full suite 70 passed / 3
  Postgres-skipped). No new ADR (Spider-subclass realization implied by ADR-0002/0003 + the
  registry precedent; demo shape is a fixture detail).

- **T1.4 — Pipeline: validate → normalize → dedup ✅** — `pipeline/normalize.py` (pure,
  Scrapy-independent) maps `RawProduct` → canonical `Product` + `PriceObservation`
  (`NormalizedItem` bundle): canonical id `{source}:{external_id}`, `raw_price` → non-negative
  finite `Decimal`, currency resolved item→source-`default_currency`→reject (never guessed),
  whitespace-collapsed titles, UTC capture stamp. `pipeline/item_pipeline.py`
  (`NormalizePipeline`, wired into `ITEM_PIPELINES`) is the Scrapy adapter: rejects non-
  `RawProduct`/unmappable items (`DropItem`, counted), dedups within a run by canonical id
  (keep-first), tracks `items_ok`/`items_rejected`/`items_duplicate`. `demo_rest` gained a
  `default_currency` ("USD"). **New: ADR-0010** (normalization + in-run dedup policy). 31 new
  tests (pure fns + pipeline adapter + demo_rest fixture round-trip); full suite 101 passed / 3
  Postgres-skipped.

- **T1.5 — Persistence + crawl-run ledger ✅** — `storage/repositories.py` adds three
  repositories over the ORM (taking canonical pydantic contracts, mapping to ORM):
  `ProductRepository.upsert` (Postgres `INSERT … ON CONFLICT (id) DO UPDATE`, refreshing
  descriptive fields + `GREATEST(last_seen_at)`, preserving `first_seen_at`);
  `PriceObservationRepository.append`/`list_for`/`count_for` (**append-only** — no update/delete);
  `CrawlRunRepository.open`/`close`/`get` (running → terminal status + item counts). Integration
  test (live Postgres, port 5544) proves a re-run appends a 2nd immutable observation and
  upserts (not duplicates) the product with `first_seen_at` preserved / `last_seen_at` advanced,
  and both runs are recorded; money round-trips as `Decimal`. Full suite **107 passed / 0
  skipped** with the DB up. No new ADR (schema/append-only/projection from ADR-0006/docs/03).

- **T1.6 — GET /products + /products/:id/price-history ✅** — two Flask read routes
  (`api/products.py`, blueprint on the config base path) per `specs/openapi.yaml`. `GET /products`
  (`source`/`q`/`limit` 1-100 default 24) and `GET /products/{id}/price-history` (`window` ∈
  30d/90d/180d/365d/all, default 90d). Responses serialized through camelCase API models
  (`api/serializers.py`, distinct from the snake_case canonical `contracts`) so `Money.amount` is
  a **string**, every response carries freshness (`dataAsOf` + `stale`, where `stale` = data
  older than the source's `stale_after_seconds`, docs/07), and each observation carries
  `capturedAt` + `sourceId`. `latestPrice`/`inStock` are derived from the newest observation at
  query time (`PriceObservationRepository.latest_for_many`, Postgres `DISTINCT ON`), never stored
  on the projection (docs/03 §2.2). Unknown product → 404 problem+json. New read methods:
  `ProductRepository.list`, `PriceObservationRepository.list_for(since=…)`/`latest_for_many`,
  `SourceRepository.stale_after_for`. 9 Flask-test-client integration tests (shape/freshness/
  latest-price/filter+search/stale/empty/window/404/400); full suite **116 passed / 0 skipped**
  with the DB up. Verified live via curl (`/products`, `/price-history`, 404). No new ADR
  (routes/serialization from ADR-0007 + openapi; freshness rule from docs/07).

- **T1.7 — End-to-end REST slice ✅ (M1 gate passed)** — the vertical slice runs end to end:
  `acquire-intel crawl demo_rest` fetches paginated `products.json` → pipeline → Postgres → the
  API serves it with freshness. New `pipeline/persistence.py` (`PersistencePipeline`, wired into
  `ITEM_PIPELINES` at 400, after normalize) writes each `NormalizedItem` via the repositories in a
  per-item transaction; the runner (`acquisition/runner.py`) now drives the **crawl-run ledger**
  for persistable sources — loads the source's `base_url`/`default_currency` from the `sources`
  registry, opens a `crawl_runs` row *before* the crawl (so the observation `run_id` FK resolves),
  passes `run_id` + config into the spider, and closes the run with a terminal status
  (`success`/`partial`/`failed`) + `items_ok`/`items_rejected` from Scrapy stats (recorded even on
  crash). The no-op `demo` source has no `kind` → still DB-free (T0.4 preserved). **A persistable
  source must be registered in `sources` first** (else exit 2, `crawl.unregistered_source`). New
  E2E test (`test_e2e_rest.py`): a real CLI subprocess crawls a local fixture HTTP server →
  asserts 2 products + observations persisted, run ledgered, and both API routes return the data
  with freshness. Full suite **117 passed / 0 skipped** with the DB up; verified live (crawl logs
  `success items_ok=2`; curl shows both routes). No new ADR (wiring follows ADR-0002/0003/0006/0010).

**Phase 1 / M1 gate: DONE.** Crawl the REST source → observations persisted → API returns them
with freshness; strict ruff/mypy/pytest green. Merged to `main` via PR #3.

### Phase 2 — More techniques (M2)

- **T2.1 — HTML extractor (Playwright) ✅** — `acquisition/sources/demo_html.py` adds
  `DemoHtmlExtractor` (`kind="html"`), the second concrete `SourceExtractor`: a `scrapy.Spider`
  whose listing request is **Playwright-marked** (`meta={"playwright": True, …
  PageMethod("wait_for_selector", "[data-product-id]")}`) so JS-rendered pages hydrate before
  parse. The HTML→`RawProduct` map is a **pure function** (`parse_products`) over rendered HTML
  using resilient `data-*` selectors, so it's fixture-tested without a browser; missing price/id
  → card skipped (never fabricated), and **selector drift** (renamed hooks) → yields nothing
  (ADR-0008, contract rule 3). `scrapy-playwright` added (ratified by ADR-0002); Scrapy settings
  enable the Playwright download handlers + asyncio reactor **globally but lazily** — the handler
  delegates non-`playwright` requests to the default downloader, so REST/GraphQL are unaffected
  and no browser launches unless a request opts in (verified: REST E2E still green). Registered as
  `demo_html`. Fixtures under `tests/fixtures/demo_html/` (rendered snapshot + expected + drifted +
  a client-rendered `js_page.html`); 12 tests incl. a **real Chromium render** smoke test (marked
  `playwright`, skips if the browser is absent; CI installs Chromium). Full suite **129 passed /
  0 skipped** locally. No new ADR (Playwright ratified by ADR-0002).

- **T2.2 — GraphQL extractor ✅** — `acquisition/sources/demo_graphql.py` adds
  `DemoGraphqlExtractor` (`kind="graphql"`), the third concrete `SourceExtractor`: a
  `scrapy.Spider` that issues a **typed** GraphQL operation (`query Products($first: Int!, $after:
  String)`) as a JSON `POST` (`scrapy.http.JsonRequest`) against a Shopify Storefront-style Relay
  connection, and follows **cursor pagination** via `pageInfo { hasNextPage endCursor }` (each
  follow-up carries the `after` cursor in its variables, kept inside the Scrapy engine so the
  shared resilience layer stays in force). The query shape is derived from the public Storefront
  API docs (documented in the module docstring per ADR-0004's follow-up), checked in and
  fixture-tested. Nodes → `RawProduct` (per-node `currencyCode` carried through, unlike REST's
  shop-level currency); robustness contract holds — a GraphQL `errors` payload / block page /
  non-JSON / wrong shape yields **nothing** and stops paging, and a node with a null
  `minVariantPrice` is skipped, never fabricated (ADR-0008). Registered as `demo_graphql`.
  Fixtures under `tests/fixtures/demo_graphql/` (page-1 with one price-less node + expected + a
  final page + a `errors` malformed response); 13 tests (protocol/identity/typed-POST/mapping/
  per-node-currency/cursor-follow/last-page-stop/4× rejection/registry). Full suite **142 passed /
  0 skipped** with the DB up. No new ADR (GraphQL ratified by ADR-0004; Spider-subclass + POST
  realization follows the REST precedent).

- **T2.3 — Three-kinds parity ✅ (M2 gate passed)** — `tests/test_three_kinds_parity.py` proves the
  headline M2 claim two ways. (1) A **parameterized integration test** (`ids=[rest, html,
  graphql]`) parses each source's checked-in fixture with its *own* extractor → `RawProduct`s, then
  drives them through the **one** shared path (`normalize` → `ProductRepository.upsert` /
  `PriceObservationRepository.append`) into Postgres; the ingest function is identical for every
  kind, per-source config the only variable. It asserts each kind yields canonical
  `{source}:{external_id}` products + one immutable observation apiece with `Decimal` money + a
  3-letter ISO currency — identical canonical shape regardless of technique. (2) A **fast
  structural guard** (`test_shared_layers_are_source_agnostic`, no DB) asserts the shared
  pipeline/storage modules (`normalize.py`, `item_pipeline.py`, `persistence.py`,
  `repositories.py`) import nothing from `acquisition.sources` and name no concrete source — so no
  per-kind branch can hide in a shared layer. Full suite **146 passed / 0 skipped** with the DB up;
  ruff/mypy clean. No new ADR (verification task; source-agnostic shared layers are the design per
  ADR-0003).

**Phase 2 / M2 gate: DONE.** All three acquisition kinds (REST/HTML/GraphQL) produce canonical
products from fixtures through one pipeline + storage; strict ruff/mypy/pytest green. Merged to
`main` via PR #4.

### Phase 3 — Resilience: the centerpiece (M3)

- **T3.1 — Adversarial mock harness ✅** — `harness/` (a new top-level dev/test package, **not**
  shipped in the wheel) is a self-contained Flask mock server the resilience layer is proven
  against (ADR-0009, docs/04 §4, docs/06 §4). Scenarios are selected by URL path
  (`GET /<scenario>/products.json`): `happy` (200 + parseable `products.json`-shaped data,
  paginated), `rate_limited` (429 + `Retry-After` for a per-identity burst, then 200),
  `block_after_n` (200 up to a per-identity budget, then 403 — a **fresh identity resets it**),
  `captcha` (200 challenge page, not data), `cookie_wall` (403 + `Set-Cookie` until the session
  cookie is carried back), `soft_ban` (200 + empty body), `drift` (200, envelope intact but item
  fields renamed → unmappable). All behaviour is **deterministic**: count-based scenarios key
  state on the caller's identity (`X-Harness-Identity` → `User-Agent` → remote addr), and
  `POST /__admin__/reset` clears counters so a test starts from a known state. `HarnessConfig`
  makes thresholds overridable. Run via `uv run python -m harness.server` (documented in
  `harness/README.md`). Wiring: pytest `pythonpath=["."]` so `harness` imports in tests; CI +
  `mypy src harness` now type-check it; `harness` added to ruff isort first-party. 12 self-tests +
  verified live (curl: 429→429→200; 200×3→403; soft-ban 200 empty). Full suite **158 passed / 0
  skipped** with the DB up. No new ADR (harness ratified by ADR-0009; scenario conventions
  documented in-module + README).

- **T3.2 — Ban/anti-bot classifier ✅** — the "never cache garbage" gate (ADR-0005, docs/04 §2.5).
  `resilience/classifier.py` is a **pure** `classify(status, body) -> Classification`
  (`ok|rate_limited|blocked|captcha|empty`): CAPTCHA/JS-challenge body markers win over status (a
  challenge served as 200 *or* 403 → `captcha`), `429` → `rate_limited`, other non-2xx → `blocked`,
  a 2xx with an **empty** body → `empty` (a silent soft-ban — distinct from a legitimate empty JSON
  array, which has a non-empty body → `ok`). `resilience/middleware.py` (`BanDetectionMiddleware`,
  wired into `DOWNLOADER_MIDDLEWARES` @585 — below HttpCompression/Redirect so it sees the final
  decompressed body) classifies every response: `ok` passes through; a ban is recorded (Scrapy
  stats `acquire/ban_events` + `acquire/ban/{kind}`, a structured log, and a `BanEvent` appended to
  the spider's `ban_events` sink for the T3.6 ledger) and **dropped via `IgnoreRequest`** so the
  extractor never sees it. Robots.txt fetches (`meta.dont_obey_robotstxt`) are never gated.
  Detection + gating only; the recorded `action_taken` (backoff/rotate) is policy that T3.3/T3.4
  execute. Proven: 19 classifier tests incl. all **7 harness scenarios** classified as expected +
  6 middleware gating tests; **verified in the real Scrapy engine** against the harness (captcha →
  0 items scraped, 1 ban recorded; happy → 3 items, 0 bans). Full suite **183 passed / 0 skipped**;
  E2E happy-path crawl unaffected. No new ADR (classifier-as-middleware ratified by ADR-0005).

- **T3.3 — Throttle, backoff, circuit-breaker ✅** (ADR-0005, docs/04 §2.3–2.4). **Throttle**:
  AutoThrottle + per-domain caps (`CONCURRENT_REQUESTS_PER_DOMAIN`, `AUTOTHROTTLE_*`) from config.
  **Backoff**: `resilience/backoff.py` is pure full-jitter exponential (`compute_delay`, seeded-RNG
  testable) honouring `Retry-After` as a floor; `BackoffRetryMiddleware` (@585, above the ban gate)
  retries **429/503** with a real `await asyncio.sleep` (the retry *decision* is a pure `plan_retry`
  so it's testable without sleeping), bounded by `max_retries` — once exhausted the response falls
  through to the ban gate. 429/503 are removed from Scrapy's built-in `RETRY_HTTP_CODES` so this is
  the single Retry-After-aware owner. **Circuit breaker**: `resilience/circuit.py` is a pure
  per-domain state machine (closed→open at a failure threshold, open refuses during a cool-down,
  half-open probe closes on success / re-opens on failure; injectable clock); `CircuitBreakerMiddleware`
  (@583) counts `blocked/captcha/empty` per domain (not rate-limits — backoff's job) and
  short-circuits requests to an open domain via `IgnoreRequest`. Middleware order (process_response
  high→low): backoff 585 → circuit 583 → ban 581. New config knobs + `ACQUIRE_*` Scrapy settings.
  Proven: 43 tests (backoff maths, circuit FSM, both middlewares incl. the real harness rate-limit
  sequence) + **verified in the real Scrapy engine** (rate_limited → 3 items, 2 backoff retries, 0
  bans). Full suite **213 passed / 0 skipped**; E2E happy path unaffected. No new ADR (ratified by
  ADR-0005).

- **T3.4 — Proxy manager + identity rotation ✅** (ADR-0011, docs/04 §2.1–2.2, docs/08).
  **Proxy pool**: `resilience/proxy.py` is a pure, clock-injectable `ProxyPool` — round-robin over
  healthy proxies with per-proxy success/failure tallies; a banned proxy is quarantined for a
  cool-down and skipped until it elapses; a **zero-proxy pool = direct connection** (right for
  local runs + the harness), and if every proxy is cooling down it degrades to direct rather than
  fail the crawl. Proxies come only from config/env (`PROXY_URLS`), never hardcoded. **Identity**:
  `resilience/identity.py` models a *coherent* bundle (`BrowserProfile`: UA + the header profile /
  client hints / viewport / locale that browser genuinely sends — a mismatched bundle is itself a
  bot signal) and a deterministic `IdentityPool` that rotates the **whole** bundle at once with a
  fresh per-identity cookie jar (a rotated identity never carries the abandoned one's cookies).
  **Wiring**: `IdentityRotationMiddleware` (@582, between the circuit breaker @583 and the ban gate
  @581) is **respectful by default** — keeps the honest contact `USER_AGENT` and stamps no browser
  identity until a source actively blocks us (only attaches a pool proxy). On a *persistent* block
  (`blocked`/`captcha`/`empty`) it **escalates** — swaps to a coherent browser identity + fresh
  proxy and retries rather than letting the ban gate drop it (the harness keys its budget on the
  identity, so a fresh one resets it); a `blocked`+`Set-Cookie` **cookie wall** is instead retried
  with the *same* identity so `CookiesMiddleware` replays the session cookie; `rate_limited` never
  rotates (backoff owns it). Both recoveries are bounded per request (`ROTATION_MAX_ATTEMPTS`), then
  fall through to the ban gate. Proven: 18 tests incl. the **real harness** `block_after_n` (rotate
  → data served) and `cookie_wall` (replay cookie) sequences + proxy health/quarantine FSM. Full
  suite **231 passed / 0 skipped** with the DB up; ruff + mypy clean; E2E happy path unaffected.
  **New: ADR-0011** (proxy pool + coherent identity rotation, escalate-on-block).

- **T3.5 — Data-quality gates ✅** (ADR-0012, docs/04 §3, docs/03 §3). The FR-9 "never silently
  store garbage" gates, on top of shape validation (`RawProduct`/`normalize`, ADR-0008/0010).
  `pipeline/quality.py` is **pure** (`check_range`, `check_continuity`, `check_volume` +
  `GateThresholds.from_settings` + a `QualityIssue` StrEnum). **Per-item gates** (range =
  plausible price band; continuity = a product's price may not jump more than `max_jump_ratio`
  vs. its last committed price) run in `QualityGatePipeline` (@350, between normalize @300 and
  persistence @400): a failing item is **dropped + counted** (`items_rejected` +
  `acquire/quality/{issue}`), never persisted — priors are preloaded once per source at
  `open_spider`. The **run-level volume gate** can only honour "quarantined, *not committed*"
  (append-only store has no delete) by deferring the write, so `PersistencePipeline` is now
  **run-atomic**: it **buffers** survivors and at `close_spider` compares the count to the
  source's recent committed baseline (`CrawlRunRepository.baseline_count`); within tolerance →
  flush all, else → **commit nothing** and record the anomaly. A quarantined run is a first-class
  ledger status (`RunStatus` gained `quarantined`, no migration — a string column; the runner
  maps the stat → `status="quarantined"`, `items_ok=0`). Config knobs +
  `ACQUIRE_QUALITY_*` Scrapy settings. Proven: 20 tests (13 pure boundary tests + 7 pipeline,
  incl. a **real-Postgres** proof that a volume-anomalous run stores **zero** rows and is flagged
  `quarantined`). Full suite **251 passed / 0 skipped** with the DB up; ruff + mypy clean; E2E
  happy path unaffected. **New: ADR-0012**.

- **T3.6 — Resilience integration ✅ (M3 gate passed)** (docs/06 §4, docs/03 §2.4). The
  milestone-closing proof that the whole stack works end-to-end against the adversarial harness.
  **Ban ledger wired**: a new `BanEventRepository` persists the run's detected `BanEvent`s to the
  `ban_events` table; the runner passes a shared `ban_events` sink to the spider (the
  `BanDetectionMiddleware` fills it — no middleware→storage coupling) and, on close, records the
  rows + the count on the `crawl_runs` ledger. **Integration test** (`test_resilience_integration.py`,
  the harness in a thread, a real `acquire-intel crawl` subprocess per scenario into Postgres):
  `happy` / `rate_limited` (backoff) / `block_after_n` (identity rotation, `block_after=1`) each
  recover the **full catalogue** (3 observations); `captcha` / `soft_ban` persist **0** observations
  and land a `ban_events` row with the right kind (`captcha` / `empty`) and action (`rotate_identity`);
  every ban scenario proves the "**0 rows in `price_observations` from a blocked/invalid response**"
  invariant, and the ledger's `ban_events` count matches the audit rows. `cookie_wall`/`drift`
  recovery stay covered at the unit level (`test_rotation_middleware`, extractor drift fixtures).
  Full suite **256 passed / 0 skipped** with the DB up; ruff + mypy clean. No new ADR (integration
  task; ban-event persistence follows ADR-0006 + docs/03 §2.4).

**Phase 3 / M3 gate: DONE.** The resilience layer recovers from rate-limits/blocks/soft-bans,
records the ban audit trail, and never persists a blocked/invalid/quarantined response — proven
end-to-end against the harness. **Merged to `main` via PR #5.** **Next: Phase 4 (M4) — intelligence
+ hardening** (price history/deals, dashboard, scheduler + admin trigger, metrics, change detection).

### Phase 4 — Intelligence + hardening (M4)

- **T4.1 — Price history + deals ✅** (ADR-0013, docs/07, FR-17/FR-13). Deal detection + `GET /deals`.
  `analytics/deals.py` is **pure** (`compute_deal`/`rank_deals` over lightweight `PricePoint`s): a
  **deal** is a product whose latest price is ≥ `DEAL_MIN_DROP_PCT` (default 10%) below its **recent
  high** — the max price in a `DEAL_WINDOW_DAYS` (default 90) window of the product's *own* history
  (never a cross-product comparison). Ranked by drop magnitude (ties by `product_id` → deterministic),
  capped at `limit` (1–50, default 20), optional `source` filter. New `PriceObservationRepository.
  history_since` + `ProductRepository.get_many`; new `DealOut`/`DealsResponse` serializers (camelCase,
  string money, shared `dataAsOf`+`stale` freshness); `deals_bp` registered on the API base path. Each
  deal carries `previousPrice`/`currentPrice`/`dropPct`/`since` so the drop is fully traceable. 12
  tests (9 pure boundary + 3 Flask-client integration vs. Postgres: ranking, `source`/`limit` filters,
  empty). Full suite **268 passed / 0 skipped** with the DB up; ruff + mypy clean. **New: ADR-0013**
  (deal = drop vs. the product's own recent high).

**Next: T4.2 — change / selector-drift detection**: flag when a source's output shape/volume shifts
(alert, don't crash) — a drifted fixture raises a flagged run, not a silent bad crawl (FR-16).

> Phase 4 is being built on the `phase-4-intelligence` branch; PR #6 targets `main` directly
> (Phase 3 merged via #5). The Phase 4 PR accumulates M4 tasks and merges when the phase completes.
