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
uv run ruff check . && uv run mypy src     # lint + typecheck
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

**Phase 0 & Phase 1 (M1) complete (merged to `main`); Phase 2 (M2) in progress — the HTML
(Playwright) extractor lands (T2.1 ✅); GraphQL (T2.2) + three-kinds parity (T2.3) next.** The
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

**Next: T2.2 — GraphQL extractor** (`kind="graphql"`): typed query construction + variables +
cursor pagination, nodes → `RawProduct`s; fixtures (response + expected + malformed → rejected).
Then T2.3 three-kinds parity (the M2 gate).
