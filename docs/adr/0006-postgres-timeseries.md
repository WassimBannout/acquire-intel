# ADR-0006: PostgreSQL + SQLAlchemy; append-only price observations

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Architect, Data Engineer
- **Related:** docs/03-data-model.md, PRD FR-12

## Context
Price intelligence needs history, concurrent writes from the crawler, real indexing, and an
audit trail (crawl runs, ban events). We want a robust relational store with a typed ORM and
migrations.

## Decision
We will use **PostgreSQL 16** with **SQLAlchemy 2.0** (typed models) + **Alembic**
migrations. Price data is stored as an **append-only `price_observations`** time-series, with
a derived `products` projection and `crawl_runs`/`ban_events` audit tables.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| Postgres + SQLAlchemy (chosen) | Robust, concurrent, great indexing, migrations, ubiquitous | Needs a running DB (Docker Compose solves it) |
| SQLite | Zero setup | Weak concurrency; not a "scalable pipeline" story |
| MongoDB | Flexible documents | Weaker relational/audit modeling; less typical for this pipeline |
| Dedicated TSDB (Timescale/Influx) | Purpose-built | Extra infra; Postgres is sufficient at v1 volume (Timescale is a later ADR) |

## Consequences
- Positive: real relational history + audit; `docker compose up` for local; migrations keep
  schema honest; typed models pair with pydantic.
- Negative: a DB dependency (mitigated by Compose/testcontainers).
- Follow-up: indexes per docs/03 §4; consider partitioning/Timescale if volume grows (ADR).

## Notes
Observations are immutable; `products` is a rebuildable upsert projection. Money is
`NUMERIC`→`Decimal` + currency, never float.
