# ADR-0008: pydantic validation at every boundary; shared models as the contract

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Architect, Acquisition Engineer
- **Related:** docs/03 §5, docs/04 §2, specs/data-contracts/

## Context
Ingested web data is untrusted by default. Without runtime validation, a collector will
happily store a block/CAPTCHA/empty page as if it were a product — the single worst failure
mode of naive scrapers. Type hints alone don't catch this at runtime.

## Decision
We will define canonical shapes once as **pydantic v2 models** and validate at **every
boundary**: HTTP requests, environment config (`pydantic-settings`), and every extractor's
normalized output. Published **JSON Schemas** in `specs/data-contracts/` mirror the pydantic
models (parity test).

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| pydantic everywhere (chosen) | One definition → runtime validation + types; catches garbage at the edge | Small runtime cost (negligible) |
| Type hints only | Zero runtime cost | No runtime safety — junk/blocked data slips through |
| jsonschema/ajv | Language-agnostic | Less ergonomic in Python; two representations |

## Consequences
- Positive: blocked/garbage/invalid payloads are rejected before storage; a schema change
  updates validation + types together; contracts are published.
- Negative: models must evolve with the shapes (a feature).
- Follow-up: parity test pydantic ↔ JSON Schema; wire validation into the Scrapy pipeline.

## Notes
Validation failure at an extractor/pipeline boundary must **reject the item and record it**
in the crawl run — never degrade to storing partial data. This, with ban detection
(ADR-0005), is the core defense against caching garbage.
