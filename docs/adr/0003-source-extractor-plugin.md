# ADR-0003: Pluggable sources via a SourceExtractor protocol

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Architect, Acquisition Engineer
- **Related:** specs/extractor-interface.md, docs/02 §5, PRD FR-2/3/4

## Context
Value grows with the number of sources, and we deliberately span three acquisition kinds
(HTML, REST, GraphQL). Source-specific fetch/parse must not leak into the resilience,
pipeline, or storage layers.

## Decision
We will define a single **`SourceExtractor`** protocol (with `kind: html|rest|graphql`) that
each source implements as one module, registered in a source registry. Extractors emit
source-native `RawProduct`s; shared layers handle everything else.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| SourceExtractor protocol (chosen) | Add a source = one module + registration; uniform resilience/pipeline; testable via fixtures | Requires a canonical normalization contract upfront |
| One bespoke Scrapy spider per source, ad hoc | Fast to start | Duplicated resilience/parse/persist; regressions; untestable |
| Config-only declarative scraper | No code per source | Too rigid for GraphQL/JS/anti-bot nuance |

## Consequences
- Positive: sources are isolated and fixture-tested; the three kinds share one pipeline;
  the `kind` field drives request building.
- Negative: every extractor must map to the canonical `Product`/`PriceObservation`.
- Follow-up: registry + per-source config (rate, concurrency, robots, stale_after).

## Notes
An extractor that cannot produce valid items must reject/raise, never emit partial garbage —
this is enforced by the pipeline's validation + quality gates (ADR-0008).
