# Phase 1 — First Vertical Slice (REST) Prompts

One REST source, end-to-end, with freshness. Governing specs: `specs/extractor-interface.md`,
`specs/data-contracts/`, `specs/openapi.yaml`, `docs/03`, ADR-0003/0004/0006/0008.

---

## T1.1 — SourceExtractor contract + RawProduct
```
Task T1.1. Read: specs/extractor-interface.md, docs/adr/0003, docs/adr/0008,
specs/data-contracts/raw-product.schema.json.
Goal: define the SourceExtractor Protocol and RawProduct pydantic model in acquisition/.
Add a parity test asserting RawProduct matches the JSON Schema.
Verify: unit + parity tests (valid accepted, invalid rejected).
```

## T1.2 — Canonical models + contract parity
```
Task T1.2. Read: docs/03-data-model.md, specs/data-contracts/{product,price-observation,
crawl-run}.schema.json.
Goal: pydantic Product, PriceObservation, Money (Decimal + ISO-4217 currency), CrawlRun,
BanEvent. Parity tests vs the JSON Schemas.
Constraints: money is Decimal+currency, never float; timestamps UTC.
Verify: unit + parity tests.
```

## T1.3 — REST extractor
```
Task T1.3. Read: specs/extractor-interface.md, docs/adr/0004, docs/04 §1.
Goal: a REST SourceExtractor (kind="rest") that fetches paginated JSON and yields RawProducts,
with rate-limit-aware requests (delegating throttle/retry to the shared layer later).
Add fixtures under tests/fixtures/<id>/: a real payload + expected RawProducts + a malformed
payload.
Verify: fixture tests — valid → correct RawProducts; malformed → yields nothing (no junk).
```

## T1.4 — Pipeline: validate → normalize → dedup
```
Task T1.4. Read: docs/03 §3, docs/adr/0008.
Goal: a Scrapy item pipeline: pydantic-validate RawProduct → normalize to Product +
PriceObservation (Decimal money, canonical id {source}:{external_id}, UTC captured_at) →
dedup within a run. Invalid/unmappable items are rejected and counted, never stored.
Verify: unit tests — normalization correct; invalid rejected+counted; dups collapsed.
```

## T1.5 — Persistence + crawl-run ledger
```
Task T1.5. Read: docs/adr/0006, docs/03 §2.
Goal: repositories to upsert products and append immutable price_observations; open/close a
crawl_run recording status + items_ok/items_rejected.
Verify: integration test (Postgres) — re-run appends observations + upserts product; run
recorded.
```

## T1.6 — GET /products + /price-history
```
Task T1.6. Read: specs/openapi.yaml (listProducts, getPriceHistory).
Goal: implement both routes per spec, with dataAsOf + per-observation capturedAt + sourceId;
404 for unknown product. Validate response shape against the pydantic models.
Verify: Flask test-client integration tests (spec conformance, freshness, 404).
```

## T1.7 — End-to-end REST slice
```
Task T1.7. Read: plan/milestones.md (M1).
Goal: wire it so `acquire-intel crawl <rest_source>` collects → pipeline → Postgres → API
serves it.
Verify: run the crawl; show observations in Postgres; curl /products and /price-history and
show responses with freshness. (M1 gate)
```

## Phase 1 gate
Crawl the REST source → observations persisted → API returns them with freshness. Update
backlog + CLAUDE.md status.
