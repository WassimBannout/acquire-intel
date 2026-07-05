# Data Contracts

Language-agnostic **JSON Schema** definitions of the canonical entities. These are the
*published* contracts; the runtime source of truth is the matching **pydantic** models in
`src/acquire_intel/`. A parity test (docs/06) asserts they never diverge (ADR-0008).

| Contract | Describes | Used by |
|----------|-----------|---------|
| `raw-product.schema.json` | Source-native extractor output (pre-normalization) | extractors → pipeline |
| `product.schema.json` | Canonical product projection | `/products`, `products` table |
| `price-observation.schema.json` | One immutable price capture | `/price-history`, `price_observations` table |
| `crawl-run.schema.json` | Collection attempt + ban events (audit/health) | `/health/sources`, `crawl_runs` table |

**Rule:** change the contract here (and the pydantic model) *before* changing code that
produces or consumes the shape.

**Money:** always `{ amount (Decimal-as-string), currency (ISO-4217) }` — never a float.
