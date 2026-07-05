# Spec — The SourceExtractor Contract

*The single extension point for adding a data source. Implemented in
`src/acquire_intel/acquisition/`. Governs ADR-0003. Emitted items flow through the shared
resilience + pipeline + storage layers.*

## Concept

A **source** is any place we collect product/price data from. Each source is one
`SourceExtractor` of a `kind`:

- `rest` — a JSON/REST endpoint (e.g. a store's `products.json`)
- `graphql` — a GraphQL endpoint (e.g. a Storefront API)
- `html` — a JS-rendered page fetched via Playwright

The extractor owns **only** source-specific concerns: *what to request* and *how to turn a
response into `RawProduct`s*. It does **not** manage proxies, throttling, retries,
validation, or storage — those are shared layers.

## Interface (target shape)

```python
from typing import Protocol, Iterable, Literal
from datetime import timedelta

class SourceExtractor(Protocol):
    id: str                                  # unique, stable: "demo_rest"
    kind: Literal["html", "rest", "graphql"]
    stale_after: timedelta                   # freshness budget for this source

    def start_requests(self) -> Iterable["Request"]:
        """Initial requests (list/search/paginated entry points)."""

    def parse(self, response) -> Iterable["RawProduct"]:
        """Turn a (validated-as-not-banned) response into source-native RawProducts.
        May yield follow-up Requests for pagination.
        MUST NOT return partial/garbage: if the expected shape is absent, yield nothing
        and let the pipeline record a rejection; raise only on unexpected internal errors.
        """
```

### `RawProduct` (source-native, pre-normalization)

```python
class RawProduct(BaseModel):        # pydantic
    external_id: str                # source's own id/sku/handle
    title: str
    url: str
    raw_price: str | float | int    # source-native; normalized to Decimal later
    currency: str | None            # if the source states it
    in_stock: bool | None
    brand: str | None = None
    image_url: str | None = None
    extra: dict = {}                # anything source-specific
```

The **pipeline** normalizes `RawProduct` → canonical `Product` + `PriceObservation`
(`specs/data-contracts/`), applying Decimal money + currency, canonical id
(`{source_id}:{external_id}`), UTC `captured_at`, and quality gates.

## Rules (must hold)

1. **Kind-appropriate requests.** `rest`/`graphql` build API requests; `html` uses a
   Playwright request. The resilience middlewares apply to all uniformly.
2. **No cross-layer concerns.** No proxy/throttle/retry/DB code in an extractor.
3. **Never emit garbage.** Missing expected fields → yield nothing for that item (pipeline
   records a rejection). Do not fabricate defaults for a missing price.
4. **Validate your own output.** Emit `RawProduct` (pydantic) — invalid instances can't be
   constructed.
5. **Pagination via follow-up requests**, not by fetching outside the Scrapy engine (keeps
   resilience/throttling in force).
6. **Register** the extractor in the source registry with its per-source config (rate,
   concurrency, robots policy, `stale_after`).
7. **Ship fixtures.** A checked-in real payload + expected normalized output
   (`tests/fixtures/<id>/`) and a malformed/blocked payload proving rejection.

## Adding a source (checklist)

- [ ] New module `acquisition/sources/<id>.py` implementing `SourceExtractor`.
- [ ] Per-source config entry (kind, base_url, rate, concurrency, robots, stale_after).
- [ ] Register in the source registry.
- [ ] Fixtures: valid payload + expected output + malformed/blocked payload.
- [ ] Tests green (parse fixtures; harness resilience still passes); ToS/robots reviewed
      (`docs/08`).
