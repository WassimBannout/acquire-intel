# Phase 3 — Anti-Bot Resilience Prompts (the centerpiece)

The headline. Build the resilience layer and prove it against the adversarial harness.
Governing specs: **`docs/04-acquisition-and-antibot.md`**, ADR-0005/0009, `docs/06` §4,
`docs/08` (responsible crawling).

> This is the antibot-specialist's domain. Every task here is proven **against the harness**,
> never a live site. The universal assertion: **zero blocked/invalid responses are ever
> persisted.**

---

## T3.1 — Adversarial mock harness
```
Task T3.1. Read: docs/adr/0009, docs/06 §4, docs/04 §4.
Goal: build harness/ — a controllable mock server with selectable, deterministic scenarios:
happy, 429+Retry-After, 403-block-after-N-per-identity, CAPTCHA/JS-challenge page, cookie-wall
(requires a cookie), soft-ban (200+empty), selector/shape drift. It serves product-like data
on the happy path so extractors can parse it.
Verify: harness self-tests — each scenario behaves deterministically and is documented.
```

## T3.2 — Ban / anti-bot classifier
```
Task T3.2. Read: docs/04 §2.5, docs/adr/0005.
Goal: a classifier (resilience/) that labels each response ok | rate_limited | blocked |
captcha | empty using status + body markers + size + redirect-to-challenge. Emit a BanEvent;
a non-ok response is NEVER passed to an extractor. Wire as a Scrapy downloader middleware.
Verify: unit tests (fixtures for each label) + harness tests. Assert a blocked/CAPTCHA
response never reaches the extractor and is recorded as a BanEvent.
```

## T3.3 — Throttle, backoff, circuit-breaker
```
Task T3.3. Read: docs/04 §2.3–2.4.
Goal: AutoThrottle + per-domain concurrency/delay caps from source config; exponential
backoff + jitter honoring Retry-After; bounded retries; a per-domain circuit breaker that
cools down after repeated blocks. Middlewares.
Verify: harness 429 scenario → backoff then success; repeated-block scenario trips the
breaker. Unit-test backoff math + jitter bounds (deterministic with seeded RNG).
```

## T3.4 — Proxy manager + identity rotation
```
Task T3.4. Read: docs/04 §2.1–2.2, docs/08 (secrets/policy).
Goal: a proxy pool manager (health/cooldown tracking; works with zero proxies = direct) and
coherent identity bundles (UA + matching headers + cookie jar + Playwright fingerprint) that
rotate on ban or per session. Proxies/identities come from config/env, never hardcoded.
Verify: harness 403-after-N scenario → identity/proxy rotates → success with a fresh identity;
rotations recorded. Assert identity bundles stay internally consistent.
```

## T3.5 — Data-quality gates
```
Task T3.5. Read: docs/04 §3, docs/03 §3.
Goal: pipeline gates — shape (pydantic), range (plausible price/values), volume (±X% vs the
source's prior run), continuity (per-product jump threshold). Anomalies are quarantined and
recorded, never silently stored.
Verify: unit + integration — anomalous volume/range quarantined + counted; nothing garbage
persisted.
```

## T3.6 — Resilience integration (M3 gate)
```
Task T3.6. Read: plan/milestones.md (M3), docs/06 §4.
Goal: a full crawl against the harness exercising every scenario end-to-end.
Verify: all scenarios green; ban_events recorded with correct kinds/actions; and a DB
assertion that ZERO rows in price_observations originated from a blocked/invalid response.
(M3 gate)
```

## Phase 3 gate
All harness scenarios green; ban events measured; zero garbage persisted; quality gates
active. This is the interview-winning milestone — make sure the crawler-health/ban-rate
metrics are emitted. Update backlog + CLAUDE.md status.
