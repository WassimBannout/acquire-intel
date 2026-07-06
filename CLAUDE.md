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

**Phase 0 complete; Phase 1 (M1) in progress — first vertical slice: REST.** The app is built
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

**Next: T1.2 — Canonical models + contract parity** (`Product`, `PriceObservation`,
`Money(Decimal+currency)`, `CrawlRun`, `BanEvent`; docs/03, ADR-0008).
