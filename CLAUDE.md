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
docker compose up -d                 # Postgres (+ app) for local dev
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

Greenfield. No application code exists yet — only this kit. Start at **Phase 0** in
`plan/execution-playbook.md`. Update this line as milestones land.
