# ADR-0004: First-class REST and GraphQL extractors

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Acquisition Engineer
- **Related:** docs/04 §1, ADR-0003, PRD FR-2/FR-4

## Context
The target role explicitly requires extracting from **both REST and GraphQL** endpoints, not
just HTML. Many modern stores expose public JSON/REST (`products.json`) and GraphQL
(Storefront) endpoints, which are cleaner and more reliable than HTML scraping.

## Decision
We will implement REST and GraphQL as first-class extractor kinds alongside HTML: a **REST
extractor** (paginated JSON with rate-limit handling) and a **GraphQL extractor** (typed
query construction + cursor pagination + variables). Prefer these API paths when a source
offers them; fall back to HTML+Playwright otherwise.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| REST + GraphQL first-class (chosen) | Evidences the exact role skills; cleaner/more reliable data; less brittle than HTML | Two more extraction paths to build/test |
| HTML-only scraping | One path | Fails the role's REST/GraphQL requirement; more brittle |
| Third-party data API | Easy | Not "acquisition"; defeats the purpose |

## Consequences
- Positive: demonstrates API + GraphQL competency; more robust primary data path; HTML
  reserved for genuinely JS-only sources.
- Negative: GraphQL query building + pagination is fiddly (worth it — it's a headline skill).
- Follow-up: fixtures for each; document reverse-engineering a public GraphQL schema.

## Notes
GraphQL is the hardest kind to fake authentically — use a genuinely GraphQL source (e.g. a
public Storefront API) so the demonstration is real, not contrived.
