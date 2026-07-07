# ADR-0014: Change / selector-drift detection — flag a run that saw entries but couldn't map them

- **Status:** Accepted
- **Date:** 2026-07-07
- **Deciders:** Acquisition/Pipeline Engineer, Architect
- **Related:** ADR-0008 (never cache garbage), ADR-0012 (data-quality gates / volume), ADR-0009
  (harness `drift` scenario), docs/04 §3, PRD FR-16

## Context
FR-16 wants the platform to **detect and flag** when a source's output shape shifts (a renamed
field, a changed API/HTML structure) — "alert, don't crash" — rather than record a silent,
near-empty crawl as if it were normal. The failure mode is specific: the fetch *succeeds*
(200, well-formed envelope, not a ban) but the items inside no longer map to a `RawProduct`
because the fields the extractor reads were renamed. Extractors already skip unmappable items
(ADR-0008), so today such a crawl looks indistinguishable from a legitimately empty result.

## Decision
Detect drift from a **seen-vs-mapped** signal and flag the run.

- Each extractor calls `telemetry.record_parse(spider, seen=<entries in the envelope>,
  mapped=<RawProducts produced>)` per page, accumulating the Scrapy stats `acquire/entries_seen`
  and `acquire/entries_mapped`.
- After the crawl, the runner calls the pure `analytics.drift.assess_drift(seen, mapped,
  min_entries, max_unmapped_ratio)`: a run that saw at least `min_entries` entries but left more
  than `max_unmapped_ratio` of them unmapped is **drift**.
- A drifted run is ledgered with a new terminal status **`flagged`** (a plain string column, no
  migration — like `quarantined` in ADR-0012) and a `crawl.drift_detected` warning is logged.
- Status precedence (runner `_run_status`): `failed` (crash) > **`flagged`** (drift) > `quarantined`
  (volume, ADR-0012) > `partial` (some rejects) > `success`. Drift outranks a volume quarantine
  because it explains *why* the run is near-empty (a format change to fix), which is more
  actionable than "too few items".

Thresholds are config: `DRIFT_MIN_ENTRIES` (default 1), `DRIFT_MAX_UNMAPPED_RATIO` (default 0.5).

### Two flavours of drift, two signals
- **Field / envelope drift** (REST/GraphQL renamed fields; HTML card found but inner fields
  renamed): entries are *seen* but unmappable → caught here (`seen > 0, mapped ≈ 0`).
- **Container drift** (the HTML item-container selector itself vanishes, or an API stops returning
  the array): *nothing* is seen → `assess_drift` returns False by design; this surfaces as a
  **volume anomaly** vs. the source's baseline and is quarantined by ADR-0012. The two mechanisms
  are complementary and together cover "output shape/volume shifts".

## Consequences
- **No silent bad crawl:** a renamed-field source produces a `flagged` run (proven end-to-end by a
  real crawl of the harness `drift` scenario → 0 observations, `status = flagged`), not a `success`
  with 0 items.
- **Pure + cheap:** the decision is a pure function over two integers; instrumentation is one call
  per page per extractor and a no-op when there is no stats collector (unit tests unaffected).
- **A single skipped item is not drift:** the ratio + `min_entries` floor keep normal per-item
  skips (ADR-0010) from false-positiving.
- **Alerting, not blocking:** `flagged` is a signal for a human/monitoring (FR-16, docs/07); it does
  not itself change persistence. A fully-drifted crawl maps nothing, so it persists nothing anyway.

## Alternatives considered
- **Infer drift purely from item count vs. baseline:** rejected as the *primary* signal — it needs
  a baseline (misses a first-crawl drift) and can't tell a format change from a real inventory
  drop. It remains the right tool for *container* drift (ADR-0012), so we use both.
- **A dedicated `drift_events` table:** deferred — the run status + stats + log satisfy FR-16;
  per-event history can come with the metrics story (T4.4) if needed.
