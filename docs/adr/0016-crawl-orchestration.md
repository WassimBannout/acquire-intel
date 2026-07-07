# ADR-0016: One crawl orchestration for CLI, scheduler, and HTTP — subprocess launch + pre-opened ledger

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** Acquisition Engineer, Architect
- **Related:** ADR-0002 (Scrapy), ADR-0006 (crawl-run ledger), ADR-0007 (Flask + APScheduler
  follow-up: "one orchestration callable by scheduler, CLI, and HTTP"), docs/08 §4, PRD FR-15,
  specs/openapi.yaml (`triggerCrawl`)

## Context
FR-15 wants scheduled + on-demand crawls, and ADR-0007 requires the **same** orchestration behind
the CLI, the in-process APScheduler, and a token-gated `POST /admin/crawl`. The hard constraint is
Scrapy/Twisted: `CrawlerProcess.start()` boots the reactor, which **cannot be restarted** in a
process and blocks until the crawl ends. So a long-lived API/scheduler process cannot run crawls
in-process (it would run once, then block/fail forever), and `POST /admin/crawl` must not block on a
full crawl. Yet the `202` response should report a real `CrawlRun`, and every crawl must land in the
`crawl_runs` ledger exactly once.

## Decision
Split **executor** from **trigger**, and launch crawls as subprocesses.

- **Executor = the CLI** (`run_crawl`, one reactor per process). Refactored to accept an optional
  `run_id`: when supplied it **adopts** that pre-opened ledger row (skips the open, only closes it);
  when absent (a human running `acquire-intel crawl <src>`) it mints + opens its own, unchanged.
  `acquire-intel crawl <src> [--run-id ID]` exposes this; `--run-id` is internal.
- **Trigger = `acquisition/orchestrator.py::trigger_crawl(source_ids=None)`** — the one shared entry
  for the scheduler and HTTP. It resolves targets (a named source, validated against the `sources`
  registry + spider registry, or *all* registered sources), **opens a `running` `crawl_runs` row per
  target and commits**, then launches each crawl as a **detached subprocess** (`python -m
  acquire_intel.cli crawl <src> --run-id <id>`, `start_new_session=True`), and returns the running
  rows. The row is committed *before* the subprocess starts so the crawl (a separate DB connection)
  sees its own row; the subprocess adopts the id and closes it.
- **Scheduler** (`acquisition/scheduler.py`): an APScheduler `BackgroundScheduler` in the API
  process adds one interval job per registered source calling `trigger_crawl([sid])`; interval from
  `crawl_policy.schedule_seconds` else the global default. Opt-in via `SCHEDULER_ENABLED` (off by
  default so tests/CLI never auto-crawl).
- **HTTP** (`api/admin.py`): `POST /admin/crawl` is `Bearer ADMIN_TOKEN` (constant-time compare) +
  per-app rate-limited (429), delegates to `trigger_crawl`, and returns `202 {accepted, runs:[…]}`.
- The launcher is an **injectable seam** (`trigger_crawl(..., spawn=…)`, resolved at call time) so
  tests exercise resolution/ledger/HTTP without spawning Scrapy, and a real-subprocess test proves
  the end-to-end adoption.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| Subprocess launch + pre-opened ledger row (chosen) | Non-blocking `202` with a real run; process isolation; fresh reactor each time; scheduler/HTTP run the exact CLI (parity) | Process spawn cost; a subprocess that dies before closing leaves a `running` row |
| `CrawlerRunner` on a persistent reactor thread in the API | In-process, no spawn | Fragile reactor lifecycle in a WSGI app; shared failure domain; concurrency limits |
| A task queue (Celery/RQ) + worker | Scales, retries, durable | Extra infra (broker) — out of scope for a single-node v1 (docs/00 non-goals) |
| Block in the request until the crawl finishes | Simplest response | Violates `202` semantics; ties up a worker for minutes; reactor-restart problem remains |

## Consequences
- **Positive:** one code path (`trigger_crawl` → CLI) for scheduler + HTTP, and the same CLI an
  operator runs; `202` is honest (a persisted `running` row, id returned); a crawl crash can't take
  down the API; every crawl is ledgered once (opened by the trigger or the CLI, never both).
- **Trade-offs accepted:** a subprocess killed before it closes leaves a `running` row — surfaced by
  the health classifier (ADR-0015) as not-fresh, acceptable for v1 (a reaper can come later);
  background crawl logs go to the child's stdout, not captured by the API (the ledger + `ban_events`
  remain the audit of record); single-node only (no distributed scheduling — a v1 non-goal).
- **Follow-ups:** a stuck-`running` reaper/timeout; optional concurrency cap on simultaneous
  triggered crawls; durable scheduling if we outgrow in-process APScheduler.

## Notes
Never build the subprocess argv from user input — it is a fixed vector of our own ids (a uuid +
a registry key). `ADMIN_TOKEN`, rate limit, scheduler enable/interval are all config (docs/08);
never hardcode. The trigger must open+commit the ledger row **before** spawning, or the crawl's
`run_id` FK won't resolve in its own connection.
