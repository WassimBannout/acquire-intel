# Adversarial mock harness

A local, fully-controlled mock server the **resilience layer is tested against** (ADR-0009,
`docs/04` §4, `docs/06` §4). It simulates anti-bot behaviours on demand so the collector can be
driven into an exact failure mode and its recovery asserted — deterministically, with no live
hostile site and no flakiness.

## Run it

```bash
uv run python -m harness.server            # serves on http://127.0.0.1:8080
uv run python -m harness.server --port 9000
```

Then, e.g.:

```bash
curl http://127.0.0.1:8080/happy/products.json          # 200 + parseable product data
curl -i http://127.0.0.1:8080/rate_limited/products.json # 429 + Retry-After (burst), then 200
```

## Scenarios

Selected by URL path — `GET /<scenario>/products.json`. The count-based scenarios key their
state on the caller's **identity** (the `X-Harness-Identity` header, else `User-Agent`, else the
remote address), so rotating identity resets the budget — exactly as a real anti-bot system
behaves.

| Scenario | Behaviour | Proves (task) |
|----------|-----------|---------------|
| `happy` | 200 + `{"products": [...]}` in the REST shape the extractor parses; paginated (empty past the end). | baseline |
| `rate_limited` | `429` + `Retry-After` for the first `rate_limited_burst` requests per identity, then 200. | backoff → success (T3.3) |
| `block_after_n` | 200 for the first `block_after` requests per identity; `403` thereafter. A fresh identity resets the budget. | identity rotation → success (T3.4) |
| `captcha` | 200 with a JS/CAPTCHA **challenge page** (not data) — must be caught by body markers, not status. | ban classifier (T3.2) |
| `cookie_wall` | `403` + `Set-Cookie` until the session cookie is carried back, then 200. | cookie/session handling (T3.2/T3.4) |
| `soft_ban` | 200 with an **empty body** — a silent block. | ban classifier (T3.2) |
| `drift` | 200 with product-shaped data whose **item fields are renamed** — every item is unmappable. | selector-drift flag (T3.5) |

## Determinism & control

State is in-memory. Reset it between phases so a test starts from a known state:

```bash
curl -X POST http://127.0.0.1:8080/__admin__/reset   # 204; clears all per-identity counters
```

Thresholds (`rate_limited_burst`, `block_after`, `retry_after_seconds`, `page_size`,
`session_cookie`) live in `HarnessConfig` and are overridable when constructing the app via
`create_harness_app(HarnessConfig(...))` — the self-tests in `tests/test_harness.py` use small
values to make the sequences obvious.
