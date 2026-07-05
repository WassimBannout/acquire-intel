# Phase 0 — Bootstrap Prompts

Foundation: runnable, correct-but-empty skeleton. Governing specs: `docs/05-tech-stack.md`,
ADR-0001/0002/0006/0007/0008, `docs/06`, `docs/07`.

> Before starting: "Read CLAUDE.md, docs/05-tech-stack.md, and the ADRs. Confirm the target
> repo layout and record whether the app lives at `../acquire-intel-app` (sibling) or nested
> here; write it in CLAUDE.md status."

---

## T0.1 — Scaffold uv project
```
Task T0.1. Read: docs/05-tech-stack.md, docs/adr/0001-python-uv-monorepo.md.
Goal: create a uv project (pyproject.toml, src/ layout) with package src/acquire_intel/ and
empty modules config/, acquisition/, resilience/, pipeline/, storage/, analytics/, api/,
monitoring/. Configure ruff + mypy (strict). Add an `acquire-intel` CLI entrypoint stub.
Verify: `uv sync`; `uv run ruff check .`; `uv run mypy src`; `uv run acquire-intel --help`.
Show output.
```

## T0.2 — Config & env boundary
```
Task T0.2. Read: docs/adr/0008, docs/05 (env section).
Goal: config/ using pydantic-settings; parse env once, fail fast on missing required vars.
Add .env.example with every key (no values). No os.environ access outside config/.
Verify: boot with a missing required var → clear error; with valid .env → loads. Show both.
```

## T0.3 — Postgres + Docker + storage baseline
```
Task T0.3. Read: docs/adr/0006, docs/03-data-model.md.
Goal: docker-compose.yml with Postgres 16; SQLAlchemy 2.0 engine/session; Alembic baseline
migration creating sources, products, price_observations, crawl_runs, ban_events (per
docs/03, with indexes). Add a repository smoke test.
Verify: `docker compose up -d`; run migration; integration test writes+reads a row. Show it.
```

## T0.4 — Scrapy skeleton + CLI
```
Task T0.4. Read: docs/adr/0002, docs/02 §3.
Goal: embed a Scrapy project in the package; a no-op spider; wire `acquire-intel crawl
<source>` via a source registry stub; structlog JSON logging with run_id.
Verify: `uv run acquire-intel crawl demo` runs the no-op spider and logs a run. Show logs.
```

## T0.5 — Flask skeleton + health
```
Task T0.5. Read: docs/adr/0007, docs/07, specs/openapi.yaml (getHealth).
Goal: Flask app with a problem+json error handler and GET /health returning 200 when DB
reachable, 503 otherwise.
Verify: curl /health with DB up (200) and down (503); trigger a test error → problem+json.
```

## T0.6 — CI pipeline
```
Task T0.6. Read: docs/06 §6.
Goal: GitHub Actions workflow: uv sync → ruff → mypy → pytest, with a Postgres service
container.
Verify: green on a trivial PR; red on an intentional type error. Show the workflow.
```

## Phase 0 gate
`docker compose up` + `uv run` boot; `/health` reflects DB; CI green. Update backlog +
CLAUDE.md status.
