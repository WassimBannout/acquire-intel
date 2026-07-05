# 05 — Technology Stack & Rationale

*Owner: Senior Developer + Architect. Decisions ratified in `docs/adr/`.*

Chosen to (a) match the target role's toolchain exactly, (b) be reliably implementable and
self-verifiable by an AI agent, and (c) stay boring and well-documented.

## Stack summary

| Layer | Technology | Why | ADR |
|-------|-----------|-----|-----|
| Language | **Python 3.12+** | Role requirement; the data-acquisition lingua franca | ADR-0001 |
| Packaging / env | **uv** + `pyproject.toml` (src layout) | Fast, reproducible, modern; simple for agents | ADR-0001 |
| Crawl framework | **Scrapy** | Role requirement; scheduler, concurrency, middlewares, item pipelines | ADR-0002 |
| Headless browser | **Playwright** (`scrapy-playwright`) | Role requirement; JS rendering under Scrapy | ADR-0002 |
| REST/GraphQL extraction | Scrapy `Request` + `gql`/manual queries | Role requirement (REST + GraphQL) | ADR-0004 |
| Extractor abstraction | `SourceExtractor` protocol | Pluggable sources; one contract for html/rest/graphql | ADR-0003 |
| Resilience | Custom middlewares + `resilience/` module | The anti-bot centerpiece | ADR-0005 |
| Validation | **pydantic v2** | One model → types + runtime validation at every boundary | ADR-0008 |
| Config | **pydantic-settings** | Typed env parsing, fail-fast | ADR-0008 |
| DB | **PostgreSQL 16** | Robust time-series-friendly relational store | ADR-0006 |
| ORM | **SQLAlchemy 2.0** (+ Alembic) | Typed models, migrations | ADR-0006 |
| API | **Flask** (+ pydantic serialization) | Requested; simple; role-appropriate (API is minor) | ADR-0007 |
| Dashboard | Jinja + Chart.js (served by Flask) | Light price/health visuals without an SPA | ADR-0007 |
| Scheduling | **APScheduler** in-process (or cron) | On-demand + scheduled crawls | ADR-0007 |
| Adversarial harness | Flask/Starlette mock server | Deterministic anti-bot testing | ADR-0009 |
| Logging | **structlog** | Structured JSON logs, run/request context | docs/07 |
| Tests | **pytest** (+ pytest-asyncio) | Unit + integration + harness | docs/06 |
| Lint/format/type | **ruff** + **mypy** | Consistent, typed, agent-friendly | — |
| Containers | **Docker Compose** | Postgres + app locally; reproducible | docs/02 |
| CI | **GitHub Actions** | lint + type + test on PR | docs/06 |

## Why these specifically

- **Scrapy + Playwright** are named in the target role; using them (not `requests`+`bs4`) is
  the point. Scrapy also gives us the middleware seam where the resilience layer naturally
  lives — architecture and skills-demonstration align.
- **uv** makes the project reproducible and fast to set up, which matters for an
  agent-built repo and for a reviewer cloning it.
- **PostgreSQL** over SQLite because price history + concurrent writes + real indexing is
  part of the "scalable pipeline" story; Docker Compose keeps it one command.
- **Flask** (your call) is fine: the web layer is a thin read/serve surface; the engineering
  weight is in acquisition. pydantic handles validation regardless of framework.
- **pydantic everywhere** kills the "stored a block page as data" bug class at the boundary.

## Repo layout (target — created in Phase 0)

```
acquire-intel-app/            # the built app (Phase 0); sibling of this kit or nested
├── pyproject.toml            # uv-managed
├── .env.example
├── docker-compose.yml        # postgres (+ app)
├── src/acquire_intel/
│   ├── config/               # pydantic-settings, per-source config
│   ├── acquisition/          # scrapy project, spiders, extractors (html/rest/graphql)
│   ├── resilience/           # proxy mgr, identity, throttle, backoff, ban-detect, middlewares
│   ├── pipeline/             # validate, normalize, dedup, quality gates (scrapy item pipelines)
│   ├── storage/              # SQLAlchemy models, repositories, alembic
│   ├── analytics/            # price history, deals, change detection
│   ├── api/                  # Flask app, routes, dashboard (jinja + chart.js)
│   └── monitoring/           # crawl-run health, metrics
├── harness/                  # adversarial mock server (tests)
└── tests/                    # unit + integration + harness-driven
```

> The kit (`acquire-intel/`) and the app are separate. Phase 0 scaffolds the app and
> records whether it lives at `../acquire-intel-app` or nested here.

## Dependency discipline
- Load-bearing deps require an ADR (Scrapy, Playwright, Postgres, Flask, pydantic).
- Prefer stdlib before adding a package. Pin majors; commit the `uv.lock`.
- No dependency reads env outside `config/`.

## Environment variables (`.env.example`, Phase 0)

```
# database
DATABASE_URL=postgresql+psycopg://acquire:acquire@localhost:5432/acquire

# api
FLASK_SECRET_KEY=
ADMIN_TOKEN=                     # gates on-demand crawl trigger
API_BASE_PATH=/api/v1

# acquisition
CONTACT_USER_AGENT=AcquireIntelBot/0.1 (+contact@example.com)
ROBOTSTXT_OBEY=true
PROXY_POOL=                      # comma-separated proxy URLs; empty = direct
DEFAULT_DOWNLOAD_DELAY=1.0
AUTOTHROTTLE_ENABLED=true

# harness (tests)
HARNESS_BASE_URL=http://localhost:8999
```
