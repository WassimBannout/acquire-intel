# Backlog — Sliced, Acceptance-Tested Tasks

*Owner: Senior Developer. Each task is small, independently verifiable, and references the
PRD requirement it serves. Work top-to-bottom within a phase. New tasks use
`templates/task-template.md`.*

**Legend:** `[ ]` todo · `[~]` in progress · `[x]` done. Each task: **Goal → Acceptance →
Verify**. Done only when it passes the verification gate (`docs/06` §5).

---

## Phase 0 — Foundation (M0)

### T0.1 — Scaffold uv project
- **Goal:** uv `pyproject.toml`, `src/acquire_intel/` package with concern-modules
  (`config, acquisition, resilience, pipeline, storage, analytics, api, monitoring`), ruff +
  mypy config, `acquire-intel` CLI entrypoint stub.
- **Acceptance:** `uv sync` installs; `uv run ruff check .` and `uv run mypy src` pass on
  stubs; `uv run acquire-intel --help` prints.
- **Verify:** run all three. (ADR-0001)

### T0.2 — Config & env boundary
- **Goal:** `config/` using pydantic-settings; parse env, fail fast on missing required;
  `.env.example` with all keys (docs/05). No `os.environ` elsewhere.
- **Acceptance:** missing required var → clear startup error; valid `.env` → loads.
- **Verify:** run both cases. (ADR-0008)

### T0.3 — Postgres + Docker + storage baseline
- **Goal:** `docker-compose.yml` (Postgres); SQLAlchemy 2.0 engine/session; Alembic baseline
  migration for `sources/products/price_observations/crawl_runs/ban_events`.
- **Acceptance:** `docker compose up -d` + migration creates tables; a smoke repository test
  writes/reads a row.
- **Verify:** integration test against the compose Postgres. (ADR-0006, docs/03)

### T0.4 — Scrapy skeleton + CLI
- **Goal:** Scrapy project embedded in the package; a no-op spider; `acquire-intel crawl
  <source>` wiring (registry stub); structured logging (structlog) with `run_id`.
- **Acceptance:** `uv run acquire-intel crawl demo` runs the no-op spider and logs a run.
- **Verify:** run it; show structured log. (ADR-0002)

### T0.5 — Flask skeleton + health
- **Goal:** Flask app, problem+json error handler, `GET /health` (200/503 by DB reachability).
- **Acceptance:** `/health` 200 when DB up, 503 when down; a thrown error → problem+json.
- **Verify:** curl both states. (ADR-0007, docs/07)

### T0.6 — CI pipeline
- **Goal:** GitHub Actions: uv sync → ruff → mypy → pytest, with a Postgres service.
- **Acceptance:** green on trivial PR; red on an intentional type error.
- **Verify:** open a PR both ways. (docs/06 §6)

---

## Phase 1 — First vertical slice: REST (M1)

### T1.1 — SourceExtractor contract + RawProduct
- **Goal:** `SourceExtractor` protocol + `RawProduct` pydantic model in `acquisition/`;
  parity test vs `specs/data-contracts/raw-product.schema.json`.
- **Acceptance:** valid accepted, invalid rejected; parity passes.
- **Verify:** unit + parity tests. (ADR-0003, ADR-0008)

### T1.2 — Canonical models + contract parity
- **Goal:** pydantic `Product`, `PriceObservation`, `Money(Decimal+currency)`, `CrawlRun`,
  `BanEvent`; parity tests vs `specs/data-contracts/`.
- **Acceptance:** money is Decimal+currency (no float); parity passes.
- **Verify:** unit + parity tests. (docs/03, ADR-0008)

### T1.3 — REST extractor
- **Goal:** a REST `SourceExtractor` (paginated JSON) with rate-limit-aware requests;
  fixtures: valid payload + expected `RawProduct`s + a malformed payload.
- **Acceptance:** valid fixture → correct RawProducts; malformed → yields nothing (no junk).
- **Verify:** fixture tests. (FR-2, ADR-0004)

### T1.4 — Pipeline: validate → normalize → dedup
- **Goal:** Scrapy item pipeline: pydantic-validate RawProduct → normalize to Product +
  PriceObservation (Decimal money, canonical id, UTC captured_at) → dedup within a run.
- **Acceptance:** normalization correct on fixtures; invalid item rejected + counted; dups
  collapsed.
- **Verify:** unit tests. (FR-7, FR-8, docs/03 §3)

### T1.5 — Persistence + crawl-run ledger
- **Goal:** repositories: upsert `products`, append `price_observations`; open/close
  `crawl_runs` (status, items_ok/rejected).
- **Acceptance:** re-running appends observations (immutable) + upserts product; run recorded.
- **Verify:** integration test against Postgres. (FR-10, FR-12, ADR-0006)

### T1.6 — GET /products + /products/:id/price-history
- **Goal:** Flask routes per `specs/openapi.yaml`, with `dataAsOf` + per-point `capturedAt` +
  `sourceId`; 404 for unknown product; validate response shape.
- **Acceptance:** spec-conformant; freshness present; 404 path works.
- **Verify:** Flask test-client integration tests. (FR-13)

### T1.7 — End-to-end REST slice
- **Goal:** `acquire-intel crawl <rest_source>` → data lands in Postgres → API serves it.
- **Acceptance:** a real (friendly) or fixture-backed crawl produces observations returned by
  the API with correct freshness.
- **Verify:** run the crawl; curl the API; show rows + response. (M1 gate)

---

## Phase 2 — More techniques (M2)

### T2.1 — HTML extractor (Playwright)
- **Goal:** an HTML `SourceExtractor` using `scrapy-playwright` for a JS-rendered page;
  fixtures (rendered HTML snapshot + expected output; a drifted snapshot).
- **Acceptance:** parses rendered fixture → RawProducts; drifted fixture → rejected.
- **Verify:** fixture tests; a real Playwright render smoke test. (FR-3, ADR-0002)

### T2.2 — GraphQL extractor
- **Goal:** a GraphQL `SourceExtractor`: typed query construction, variables, cursor
  pagination; fixtures (GraphQL response + expected; malformed).
- **Acceptance:** paginates via cursors; parses nodes → RawProducts; malformed → rejected.
- **Verify:** fixture tests. (FR-4, ADR-0004)

### T2.3 — Three-kinds parity
- **Goal:** confirm all three extractors feed the identical pipeline/storage with no
  source-specific code leaking into shared layers.
- **Acceptance:** one pipeline test runs REST/HTML/GraphQL fixtures → canonical products.
- **Verify:** parameterized integration test. (M2 gate)

---

## Phase 3 — Resilience: the centerpiece (M3)

### T3.1 — Adversarial mock harness
- **Goal:** `harness/` server with configurable scenarios: happy, 429+Retry-After,
  403-after-N-per-identity, CAPTCHA/challenge, cookie-wall, soft-ban (200+empty), drift.
- **Acceptance:** each scenario is selectable and deterministic; documented.
- **Verify:** harness self-tests. (FR-11, ADR-0009)

### T3.2 — Ban/anti-bot classifier
- **Goal:** classify responses (ok/rate_limited/blocked/captcha/empty) via status + body
  markers + size + redirects; emit `BanEvent`; blocked never passes downstream.
- **Acceptance:** deterministic classification on fixtures + harness; blocked response never
  reaches an extractor.
- **Verify:** unit + harness tests. (FR-6, docs/04 §2.5)

### T3.3 — Throttle, backoff, circuit-breaker
- **Goal:** AutoThrottle + per-domain caps; exponential backoff+jitter honoring Retry-After;
  bounded retries; per-domain circuit breaker.
- **Acceptance:** against harness 429, backoff observed then success; repeated blocks trip the
  breaker (cool-down).
- **Verify:** harness tests; unit tests for backoff math/jitter bounds. (FR-5)

### T3.4 — Proxy manager + identity rotation
- **Goal:** proxy pool manager (health/cooldown, zero-proxy ok); coherent identity bundles
  (UA/headers/cookies/fingerprint) rotating on ban/session.
- **Acceptance:** against harness 403-after-N, identity/proxy rotates → success; rotations
  recorded; identity bundles stay coherent.
- **Verify:** harness tests. (FR-5, docs/04 §2.1–2.2)

### T3.5 — Data-quality gates
- **Goal:** pipeline gates: shape (pydantic), range (price/plausibility), volume (±X% vs prior
  run), continuity (per-product jump) → quarantine/flag, never silent-store.
- **Acceptance:** anomalous volume/range quarantined + recorded; nothing garbage stored.
- **Verify:** unit + integration tests. (FR-9, docs/04 §3)

### T3.6 — Resilience integration (M3 gate)
- **Goal:** full crawl against the harness across all scenarios.
- **Acceptance:** all scenarios green; `ban_events` recorded with correct kinds/actions;
  **0 rows** in `price_observations` originate from a blocked/invalid response.
- **Verify:** end-to-end harness test asserting recovery + zero garbage. (M3 gate)

---

## Phase 4 — Intelligence + hardening (M4)

### T4.1 — Price history + deals
- **Goal:** analytics: per-product history; deals = significant drops vs. own history; `GET
  /deals`.
- **Acceptance:** deterministic drop computation on fixtures; spec-conformant endpoint.
- **Verify:** unit + integration tests. (FR-17, FR-13)

### T4.2 — Change / selector-drift detection
- **Goal:** detect and flag when a source's output shape/volume shifts (alert, don't crash).
- **Acceptance:** a drifted fixture raises a flagged run, not a silent bad crawl.
- **Verify:** tests over drifted fixtures. (FR-16)

### T4.3 — Dashboard
- **Goal:** Jinja + Chart.js: per-product price chart; crawler-health panel (ban-rate trend,
  freshness, items ok/rejected, rotations).
- **Acceptance:** renders charts + health; loading/empty states.
- **Verify:** view tests + observe running. (FR-14, docs/07 §5)

### T4.4 — /health/sources + metrics
- **Goal:** per-source health (healthy/degraded/stale/failing) from `crawl_runs`; metrics
  catalog (docs/07 §4).
- **Acceptance:** correct classification over seeded runs; ban-rate exposed.
- **Verify:** integration tests. (FR-10)

### T4.5 — Scheduler + admin crawl
- **Goal:** APScheduler per-source schedules; token-gated `POST /admin/crawl`; CLI parity.
- **Acceptance:** scheduled tick triggers a crawl; no token → 401; token → 202.
- **Verify:** integration tests; manual trigger. (FR-15, ADR-0007, docs/08)

### T4.6 — Demo & CI/CD polish
- **Goal:** README with a 5-minute demo script (compose up → run harness crawl → see charts +
  ban-rate → run API); ensure CI runs full suite; `pip-audit` in CI.
- **Acceptance:** a fresh clone can follow the README to a working demo; CI green.
- **Verify:** dry-run the README steps. (portfolio gate)

---

## Backlog hygiene
- One task in progress at a time. Reference the task id (e.g. `T3.4`) in commits.
- A task revealing a decision → write an ADR first.
- If scope grows, split the task — keep each independently verifiable.
- Prove resilience against the **harness**, never a live hostile site.
