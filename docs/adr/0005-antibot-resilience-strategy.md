# ADR-0005: Anti-bot resilience as Scrapy middlewares + a resilience module

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Acquisition Engineer, Architect
- **Related:** docs/04 (full design), ADR-0002, ADR-0009, PRD FR-5/FR-6

## Context
The defining skill of the project (and the role) is reliable collection in adversarial
environments: rate limits, blocking, anti-bot, CAPTCHAs. This must be a first-class,
uniform, testable layer — not per-spider hacks.

## Decision
We will implement resilience as a set of **Scrapy downloader middlewares** backed by a
`resilience/` module: proxy pool manager, coherent identity/fingerprint rotation, adaptive
throttling, exponential backoff+jitter, per-domain circuit breaker, and a **ban/anti-bot
classifier** that prevents blocked/garbage responses from ever reaching an extractor.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| Middlewares + resilience module (chosen) | Uniform across all requests; isolated; testable via harness; idiomatic Scrapy | Must design coherent identity rotation carefully |
| Per-spider anti-bot code | Localized | Duplicated, inconsistent, untestable; the classic mess |
| Buy a scraping API/proxy SaaS | Offloads anti-bot | Defeats the whole point — the skill is what we're demonstrating |

## Consequences
- Positive: every request is throttled, identity-rotated, retried, and classified; the layer
  is provable against the adversarial harness; ban events are measured.
- Negative: careful design needed so identity bundles stay coherent (UA/headers/fingerprint
  consistent).
- Follow-up: proxy provider abstraction (env pool, works with zero proxies); circuit-breaker
  tuning per source.

## Notes
Techniques serve **reliability on public data**, within the responsible-crawling policy
(docs/08). A classified ban is recorded and recovered from — never parsed or stored.
