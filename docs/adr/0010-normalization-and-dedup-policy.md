# ADR-0010: Normalization & in-run dedup policy

- **Status:** Accepted
- **Date:** 2026-07-06
- **Deciders:** Pipeline Engineer, Architect
- **Related:** docs/03 §3, ADR-0008, specs/data-contracts/, PRD FR-7/FR-8

## Context
The pipeline maps source-native `RawProduct`s to the canonical `Product` + `PriceObservation`
before persistence. Two forces are under-specified by docs/03 §3 and need a firm, source-
agnostic rule so every extractor behaves identically: (1) the canonical models **require** an
ISO-4217 currency, but a `RawProduct.currency` is nullable — many REST/HTML sources (e.g. a
Shopify `products.json`) state price without a per-item currency; (2) a single crawl run can
surface the same product more than once (overlapping pages, re-listings), and we must not write
redundant observations for one capture.

## Decision
We will normalize with these rules, all enforced in the shared pipeline (no source-specific
code in shared layers): **currency resolves from the item, else a source-level
`default_currency` (source config), else the item is rejected — never guessed**; prices parse
to a non-negative finite `Decimal` (numbers stringified first); titles are whitespace-collapsed
and rejected if empty; and items are **deduped within a run by canonical id
`{source_id}:{external_id}`, keep-first**. Unmappable items raise `NormalizationError` and are
dropped and counted (`items_rejected`); duplicates are dropped and counted (`items_duplicate`);
neither is ever persisted. `captured_at` is stamped at capture time and also seeds the
product's first/last-seen (persistence preserves the true `first_seen_at` on upsert).

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| Item → source-default → reject (chosen) | Source-agnostic; never fabricates a currency; correct for currency-less endpoints | Requires per-source `default_currency` config |
| Reject any item lacking an explicit currency | Simplest | Drops all data from currency-less sources (e.g. products.json) — defeats the slice |
| Assume a global default (e.g. USD) | Trivial | Silently wrong for non-USD shops; corrupts money data |
| Dedup keep-last / no dedup | — | keep-last is arbitrary for one capture; no-dedup writes redundant observations |

## Consequences
- Positive: money is always `Decimal` + a real ISO-4217 currency or the item is rejected;
  one observation per product per run; the same policy holds across REST/HTML/GraphQL.
- Negative / trade-offs accepted: each source must declare its `default_currency` (carried on
  the extractor until the `sources` table drives it in T1.5/T1.7).
- Follow-ups: range/plausibility and volume/continuity gates are **not** here — they are the
  data-quality gates in M3 (FR-9, T3.5). This ADR covers shape-normalization + in-run dedup.

## Notes
`default_currency` is source configuration, never a hardcoded target-specific value in the
pipeline. The pipeline reads it from the spider (`getattr(spider, "default_currency", None)`);
an extractor that omits it forces every currency-less item to be rejected — a safe failure.
