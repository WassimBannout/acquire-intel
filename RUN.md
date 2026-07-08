# RUN.md — how to run AcquireIntel

The short, practical guide to running the app locally. If you forget everything else, read this.
(For *what the project is*, see `README.md`; for *how it's built*, `CLAUDE.md` + `docs/`.)

---

## TL;DR

```bash
make setup     # once: writes a dev .env, starts Postgres, applies migrations
make demo      # crawl the mock adversary → demo data (deterministic; proves the anti-bot layer)
make live      # crawl a REAL Shopify store → real products + prices
make run       # start the app (JSON API + dashboard) at http://localhost:5000
```

`make run` is the whole app — one Flask process serves **both** the JSON API (`/api/v1/...`) and the
server-rendered dashboard (`/`). There is no separate frontend/backend to start. `make help` lists
every target.

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** (Python package manager) — installs Python 3.12 + deps.
- **Docker** (Docker Desktop or a running daemon) — for the Postgres database.

## First-time setup

```bash
make setup
```

This: creates a **dev `.env`** (git-ignored, dev-only values — see below), runs `uv sync`, starts
Postgres via `docker compose`, and applies DB migrations. Run it once per clone.

## Everyday commands

| Command | What it does |
|---------|--------------|
| `make run` | The app (API + dashboard) at http://localhost:5000 |
| `make demo` | Crawl the mock harness (happy + block_after_n + captcha) → source `demo_rest` |
| `make live` | Crawl a real store (default deathwishcoffee.com) → source `live_rest` |
| `make live STORE=https://www.allbirds.com CURRENCY=USD` | Crawl any store with an open `/products.json` |
| `make reset` | Wipe all crawled data (clean slate to switch demo ⟷ live) |
| `make test` | Full test suite — **⚠ wipes crawled data**, see Gotchas |
| `make db` / `make migrate` | Start Postgres / apply migrations |
| `make crawl SOURCE=demo_rest` | Crawl one already-seeded source |
| `make clean` | Stop Postgres + remove local demo artifacts |

## Demo data vs. a real store (and switching)

Same engine, different target URL. The **mock is the test adversary** that proves rotation / backoff
/ ban-detection deterministically — it is not the product.

- `make demo` → source **`demo_rest`** (mock). Deterministic; tells the resilience story.
- `make live` → source **`live_rest`** (a real Shopify store). Real catalogue + current prices,
  obeying `robots.txt`, public data only.
- They are **separate sources** and coexist on the dashboard. To show only one, `make reset` first,
  then crawl the one you want.

Real **price history** (moving charts, `/deals`) accumulates when you crawl a store repeatedly over
time — that's what the built-in scheduler (`SCHEDULER_ENABLED`) is for. A single crawl gives real
prices at one point in time.

## What to open

Once `make run` is up:

| URL | Shows |
|-----|-------|
| http://localhost:5000/ | Dashboard: products table + crawler-health panel (ban-rate, rotations) |
| http://localhost:5000/api/v1/products | Products + latest price + freshness |
| http://localhost:5000/api/v1/products/live_rest:<id>/price-history | One product's price time-series |
| http://localhost:5000/api/v1/deals | Detected price drops |
| http://localhost:5000/api/v1/health/sources | Per-source healthy/degraded/stale/failing + banRate |
| http://localhost:5000/api/v1/metrics | Crawl/ban counters + gauges |

## Environment / config

`make setup` writes a git-ignored **`.env`** with dev-only values:

```
DATABASE_URL=postgresql+psycopg://acquire:acquire@localhost:5544/acquire
FLASK_SECRET_KEY=dev-secret
ADMIN_TOKEN=dev-admin-token
```

- The app reads `.env` automatically — no manual `export`s needed.
- The DB host port is **5544** here (set by `DB_HOST_PORT`; compose default is 5432). If you change
  it, keep `DATABASE_URL` and `make db` in sync (`make setup DB_HOST_PORT=xxxx`).
- `.env` is **git-ignored on purpose** (it holds secrets / machine-local values). `.env.example`
  documents every key. Never commit a real `.env`.

## Gotchas / troubleshooting

- **"Internal server error" on every page** → Postgres is unreachable. Usually Docker stopped.
  Start Docker, then `make db`. (Data lives in a named volume `pgdata`, so it survives restarts.)
- **Dashboard is empty** → no data has been crawled (or it was wiped). Run `make demo` and/or
  `make live`.
- **`make test` wiped my data** → the test suite's integration tests `TRUNCATE` the tables and
  currently share this dev database. After running tests, re-crawl (`make demo` / `make live`).
- **"Address already in use" on port 5000** → something is already on 5000. Run on another port:
  `make run PORT=5001`.
- **`live` crawl returns 0 products** → that store's `robots.txt` may disallow `/products.json`, or
  it isn't a Shopify store. Try another store (`make live STORE=...`).

## Quality gates (before committing changes)

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src harness && make test
```
