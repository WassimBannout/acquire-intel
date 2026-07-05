# Phase 2 — More Techniques (HTML + GraphQL) Prompts

Add the HTML (Playwright) and GraphQL extractor kinds under the same contract. Governing
specs: `specs/extractor-interface.md`, ADR-0002/0004, `docs/04` §1.

---

## T2.1 — HTML extractor (Playwright)
```
Task T2.1. Read: specs/extractor-interface.md, docs/adr/0002, docs/04 §1.
Goal: an HTML SourceExtractor (kind="html") using scrapy-playwright to render a JS-heavy page
and yield RawProducts. Wait for the right content; keep selectors resilient.
Add fixtures: a rendered-HTML snapshot + expected RawProducts + a drifted snapshot.
Verify: fixture tests (parsed → RawProducts; drifted → yields nothing). Add a real Playwright
render smoke test (kept out of the default fast suite if needed).
```

## T2.2 — GraphQL extractor
```
Task T2.2. Read: specs/extractor-interface.md, docs/adr/0004, docs/04 §1.
Goal: a GraphQL SourceExtractor (kind="graphql"): build typed queries with variables, follow
cursor pagination, parse nodes → RawProducts.
Add fixtures: a GraphQL response + expected RawProducts + a malformed response.
Verify: fixture tests — paginates via cursors; malformed → rejected. Document how the query
was derived (schema introspection or public docs).
```

## T2.3 — Three-kinds parity
```
Task T2.3. Read: docs/02 §5, plan/milestones.md (M2).
Goal: confirm REST, HTML, and GraphQL extractors all feed the identical pipeline + storage,
with no source-specific logic leaking into shared layers.
Verify: one parameterized integration test runs all three fixture sets → canonical products
in Postgres. (M2 gate)
```

## Phase 2 gate
All three acquisition kinds produce canonical products from fixtures through one pipeline;
tests green. Update backlog + CLAUDE.md status.
