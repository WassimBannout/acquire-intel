# ADR-0011: Proxy pool + coherent identity rotation (escalate-on-block)

- **Status:** Accepted
- **Date:** 2026-07-07
- **Deciders:** Anti-Bot Specialist, Architect
- **Related:** ADR-0005 (resilience strategy), ADR-0009 (harness), docs/04 §2.1-2.2, docs/08
  (respectful crawling), PRD FR-5/FR-6

## Context
ADR-0005 committed to proxy rotation and *coherent* identity/fingerprint rotation as Scrapy
downloader middlewares. Two design questions were left open and must be pinned so the layer is
both effective and policy-respecting:

1. **What is an identity, and when does it rotate?** docs/04 §2.2 is explicit that an identity is
   a *coherent bundle* (User-Agent + matching header profile + cookie jar + viewport/locale), and
   that a mismatched bundle (a Chrome UA with Firefox headers, or Chrome `sec-ch-ua` client hints
   with a Firefox UA) is itself a bot signal. Rotation must swap the **whole** bundle, per
   session/ban — never a lone field, never per request.
2. **How does rotation coexist with the respectful-crawling posture?** CLAUDE.md and docs/08
   require we identify a **contact** User-Agent by default and document any exception. Presenting a
   fabricated browser identity to *every* endpoint, unprompted, contradicts that. But recovering
   from an active block needs exactly that capability.

There is also a second, distinct recovery shape the harness models: a **cookie wall** (403 +
`Set-Cookie` until the session cookie is carried back). Rotating identity there is actively wrong —
a fresh identity gets a fresh cookie jar and throws away the very cookie the server just issued, so
it can never satisfy the wall.

## Decision
**Proxy pool** (`resilience/proxy.py`, `ProxyPool`): an env-supplied pool with per-proxy
success/failure health and a quarantine cool-down. Round-robin over currently-healthy proxies; a
proxy that gets banned is quarantined for `PROXY_COOLDOWN_SECONDS` and skipped until it elapses.
**Zero proxies is a first-class case** — an empty pool (and the degenerate case where every proxy is
cooling down) yields a **direct connection**, which is exactly right for local runs and the
adversarial harness. Proxies are never hardcoded; only supplied via `PROXY_POOL`. A proxy is bound
to the current identity (acquired when the identity is adopted/rotated), not re-picked per request.

**Identity pool** (`resilience/identity.py`, `IdentityPool`): a small catalogue of *coherent*
desktop browser bundles. Each UA is paired with the headers that browser genuinely emits (Chromium
sends `sec-ch-ua` client hints; Firefox/Safari do not) plus a viewport/locale. Rotation is
deterministic round-robin with a monotonically increasing `generation`, and the per-identity key
(`{profile}#{generation}`) doubles as the Scrapy **cookie-jar key** so every rotation gets a fresh
jar and never leaks the abandoned bundle's cookies. `Accept`/`Accept-Encoding` are deliberately
**not** stamped — content negotiation belongs to the request (a GraphQL `JsonRequest` needs
`application/json`) and `Accept-Encoding` belongs to Scrapy's `HttpCompressionMiddleware`
(advertising only codecs it can decode; a forced `br` we can't decompress would corrupt the body and
fool the ban classifier).

**Escalate-on-block, not evade-by-default.** The `IdentityRotationMiddleware` (priority **582**,
between the circuit breaker at 583 and the ban gate at 581) is respectful by default: until a source
actively blocks us, requests carry the honest **contact** User-Agent (Scrapy's `USER_AGENT`, docs/08)
and **no** browser identity is stamped. Only when a response is classified as a *persistent* block
(`blocked` / `captcha` / `empty` — a soft-ban) do we escalate: swap to a coherent browser identity (+
a fresh proxy) and **retry** the request rather than let the ban gate drop it. This is the documented
exception (docs/08): identity rotation activates in response to a block on public catalog data, for
reliability, never to defeat an auth/PII wall. `rate_limited` never rotates — that is transient and
owned by `BackoffRetryMiddleware` (ADR-0005/T3.3).

**Cookie wall = same-identity retry.** A `blocked` response that carries a `Set-Cookie` is retried
with the **same** identity (same cookie jar) so Scrapy's `CookiesMiddleware` replays the freshly-set
session cookie. Rotating there would discard the cookie and loop forever.

Both recoveries are bounded by `ROTATION_MAX_ATTEMPTS` (per request, tracked in `request.meta`); once
exhausted the response falls through to the ban gate, which records the `BanEvent` and drops it — so
a genuinely-blocked source still fails cleanly and is measured, never parsed or persisted (ADR-0008).
Every rotation and cookie retry is counted in Scrapy stats and logged.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| Escalate-on-block browser identities + env proxy pool (chosen) | Respectful contact UA by default (docs/08); rotates coherently only when actually blocked; proves against the harness; zero-proxy = direct | Slightly more state (a "have we escalated yet" flag) |
| Always present a rotating browser identity | Simplest middleware | Fabricates an identity to every friendly endpoint unprompted — violates the default respectful posture |
| Rotate individual fields (just the UA) | Trivial | Incoherent bundle (Chrome UA + wrong/absent client hints) is itself a bot signal — self-defeating |
| Rotate identity on a cookie wall too | One code path | Throws away the server's `Set-Cookie`; can never satisfy the wall |
| Buy a proxy/anti-bot SaaS | Offloads the problem | Defeats the point — this layer is the competency being demonstrated (ADR-0005) |

## Consequences
- Positive: coherent, per-session/ban rotation that recovers the harness `block_after_n` (fresh
  identity resets the per-identity budget → success) and `cookie_wall` (same-identity cookie replay →
  success) scenarios deterministically; proxy health with quarantine; zero-proxy direct connection;
  rotations/cookie retries measured for the T3.6 ledger. Friendly crawls are **unaffected** — they
  keep the honest contact UA and never touch a browser identity.
- Negative / trade-offs accepted: the browser bundle catalogue is finite and static (a handful of
  desktop profiles) — enough to reset a per-identity budget, not a full fingerprint-randomisation
  engine (out of scope; Playwright fingerprint depth is a follow-up). A rotated bundle's realism is
  only as good as the checked-in profiles.
- Follow-ups: wire the recorded rotations into the `crawl_runs`/`ban_events` ledger (T3.6); optional
  per-source `default_identity`/proxy affinity; deeper Playwright fingerprint (canvas/WebGL) if a
  real target demands it.

## Notes
Escalation is triggered by the **same** ban classifier that guards persistence (ADR-0005/T3.2), so
there is one source of truth for "is this a block". Techniques serve reliability on public data
within docs/08 — a classified block is recovered from (retry under a fresh identity) or, once
attempts are exhausted, recorded and dropped. Nothing blocked is ever parsed or stored.
