# ADR-0013: Deal detection — a drop vs. the product's own recent high

- **Status:** Accepted
- **Date:** 2026-07-07
- **Deciders:** Pipeline/Analytics Engineer, Architect
- **Related:** ADR-0006 (append-only observations), docs/03 (time-series), docs/07, PRD FR-17/FR-13

## Context
FR-17 wants "deal detection: significant price drops vs. the product's own history", surfaced at
`GET /deals` (openapi). "Significant" and "vs. own history" both need pinning so the computation is
deterministic (a portfolio requirement: the same observations always yield the same deals) and
defensible.

## Decision
A **deal** is a product whose **latest** price is at least `deal_min_drop_pct` percent below its
**recent high** — the maximum price observed in a `deal_window_days` lookback window of that
product's own `price_observations`.

- `current` = the latest observation by `captured_at`.
- `reference` (the recent high) = the maximum `amount` in the window; ties break toward the most
  recent time at that high, and `since` = that observation's `captured_at`.
- `drop_pct = (reference - current) / reference * 100`, rounded to 2 dp. A product is a deal only
  when `current < reference` and `drop_pct >= deal_min_drop_pct`.
- `/deals` ranks deals by `drop_pct` descending, ties broken by `product_id` (fully deterministic),
  capped at `limit` (1–50, default 20), optionally filtered by `source`.

Thresholds are config (`DEAL_MIN_DROP_PCT` default 10, `DEAL_WINDOW_DAYS` default 90). The detection
math is a **pure** module (`analytics/deals.py`) over lightweight `PricePoint`s so every boundary is
unit-testable without a DB; the route maps observation rows → points and serializes through the
existing camelCase API models + freshness envelope.

## Consequences
- **Own-history, not cross-product:** a cheap product is not a "deal"; only a real drop from its own
  recent high is — matching FR-17 and avoiding misleading cross-product comparisons.
- **Deterministic + explainable:** each deal carries `previousPrice`/`currentPrice`/`dropPct`/`since`,
  so the drop is fully traceable to two observations.
- **A brief spike then return is not a permanent "deal":** because the reference is the *max in the
  window*, once the inflated price ages out of the window the "deal" disappears — intended.
- **Cost:** the window's observations are grouped in Python (fine at demo scale). If volume grows, a
  SQL `max()`/`DISTINCT ON` per product can replace the in-memory grouping without changing the
  contract or the pure math. Noted as a future optimization.

## Alternatives considered
- **Drop vs. the immediately-prior observation:** rejected — noisy (any tiny dip flaps), and misses
  a slow decline from a high.
- **Drop vs. an all-time high:** rejected — an ancient high makes stale "deals"; a bounded window is
  more honest about "recent".
- **A cross-product percentile / z-score:** rejected — that's "cheap products", not "this product
  dropped"; contradicts FR-17.
