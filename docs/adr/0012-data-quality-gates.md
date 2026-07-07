# ADR-0012: Data-quality gates (per-item drop vs. run-atomic volume quarantine)

- **Status:** Accepted
- **Date:** 2026-07-07
- **Deciders:** Pipeline Engineer, Architect
- **Related:** ADR-0006 (storage/append-only), ADR-0008 (never cache garbage), ADR-0010
  (normalization + dedup), docs/03 §3, docs/04 §3, PRD FR-9

## Context
FR-9 requires the pipeline to enforce **data-quality gates** — shape, price range/plausibility,
per-run volume vs. a recent baseline, and per-product price continuity — and to **quarantine or
flag** anomalies rather than silently store garbage (docs/04 §3, docs/03 §3). Shape is already
covered upstream (`RawProduct` with `extra="forbid"`, ADR-0008; `normalize` rejects unmappable
items, ADR-0010). This ADR pins the remaining three gates and, crucially, *when* each can run
given the pipeline's streaming shape and the append-only store (ADR-0006).

Two of the gates are **per-item** (range, continuity): they judge one observation in isolation and
fit the existing "reject + count, never persist" path (ADR-0008/0010). The third — **volume** — is
**run-level**: it can only be evaluated once the run's surviving item count is known (at close),
because it compares that count to the source's recent baseline. This collides with the current
per-item streaming persistence (`PersistencePipeline`, T1.7) and the append-only `price_observations`
table: if we write each observation as it arrives, a volume anomaly discovered at close **cannot be
un-committed** — the store has no delete.

## Decision

1. **A pure gate module.** `pipeline/quality.py` holds pure, I/O-free functions —
   `check_range`, `check_continuity`, `check_volume` — plus a `GateThresholds` config bundle
   (`from_settings`) and a `QualityIssue` enum (`out_of_range | discontinuous | volume_anomaly`).
   Pure so every threshold boundary is unit-testable without Scrapy or a DB, matching the
   classifier/backoff/circuit precedent (ADR-0005).

2. **Per-item gates run inline and drop (range, continuity).** A `QualityGatePipeline` (Scrapy
   adapter, ordered **350**, between normalize @300 and persistence @400) applies the range and
   continuity gates to each `NormalizedItem`. A failing item is **dropped (`DropItem`) and counted**
   (`items_rejected` + `acquire/quality/{issue}`) and never reaches persistence — identical
   semantics to an unmappable item (ADR-0008/0010). Continuity needs the product's last committed
   price; the pipeline **preloads** the source's latest amounts once at `open_spider`
   (`PriceObservationRepository.latest_amounts_for_source`), so a first-ever observation always
   passes (no prior → no jump).

3. **The volume gate makes persistence run-atomic.** Because "quarantined, **not committed**"
   (docs/04 §3) is impossible to honor after streaming writes into an append-only table,
   `PersistencePipeline` no longer writes per item: it **buffers** surviving `NormalizedItem`s and,
   at `close_spider`, evaluates the volume gate (`check_volume(count, baseline)`), where `baseline`
   is the most recent **committed** run's `items_ok` for the source
   (`CrawlRunRepository.baseline_count`). If the count is within tolerance it **flushes** the whole
   buffer (upsert + append, one short transaction per item, as before); if it breaches, it **flushes
   nothing**, records the anomaly (`acquire/quality/volume_anomaly` + `acquire/quality_quarantined`),
   and the run commits zero observations. A run is thus all-or-nothing with respect to the volume
   gate.

4. **A quarantined run is a first-class, recorded status.** `RunStatus` gains `quarantined`
   (a plain string column — no migration). The runner maps the quarantine stat → `status="quarantined"`
   with `items_ok = 0`, so the `crawl_runs` ledger is a truthful, portfolio-visible record: "we
   collected N items but the run failed the volume gate and committed nothing." Per-item drops that
   don't trip the volume gate still yield `partial` (some `items_rejected`) or `success`.

### Thresholds (config, `ACQUIRE_QUALITY_*`)
- `price_min` / `price_max` — plausible price band (catches concatenated-digit scrape errors and
  non-positive prices). Compared as `Decimal`.
- `max_jump_ratio` — a product's price may not change by more than this factor vs. its last
  committed price (either direction) or it is `discontinuous`.
- `volume_tolerance` — the run's surviving count must be within `±tolerance` of the baseline.
- `volume_min_baseline` — skip the volume gate until the baseline is at least this large, so a
  tiny/young history can't produce false quarantines.

## Consequences
- **Correct semantics:** a volume-anomalous run stores **zero** garbage rows, satisfying FR-9 and
  the "never silent-store" guardrail literally, not approximately.
- **Buffering cost:** the persistence buffer holds a run's surviving items in memory. Bounded and
  fine at demo/portfolio scale; if a source grows huge, a future ADR can switch to a staging table
  or chunked commit. Documented as a known trade-off.
- **Run atomicity:** a crash mid-run now commits nothing for that run (previously: per-item
  partial). This is *more* correct for a time-series (no half-runs) and the ledger already records
  the failure.
- **No new table:** quality outcomes are recorded on `crawl_runs` (status + counts) and Scrapy
  stats/logs; a dedicated `quality_events` table is deferred until the metrics story (T3.6/M4)
  needs per-issue history.

## Alternatives considered
- **Post-hoc flag (keep streaming writes, mark the run suspect):** rejected — it violates "not
  committed"; the garbage rows are already in the time-series.
- **Delete on anomaly:** rejected — `price_observations` is append-only (ADR-0006); no deletes.
- **Volume gate in its own pipeline:** rejected — the gate is inseparable from persistence timing;
  co-locating the buffer and the flush keeps one DB owner and one transaction boundary.
