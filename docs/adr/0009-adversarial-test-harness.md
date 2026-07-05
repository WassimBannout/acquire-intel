# ADR-0009: A local adversarial mock server for deterministic anti-bot testing

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Architect, Acquisition Engineer, QA
- **Related:** docs/04 §4, docs/06 §4, PRD FR-11

## Context
The resilience layer (ADR-0005) is the project's headline, but anti-bot behavior is
impossible to verify reliably against a live hostile site: real targets are non-deterministic,
may ban the CI runner, and can't be driven into specific failure modes on demand. An AI agent
building this cannot self-verify against something that keeps blocking it.

## Decision
We will build a **local adversarial mock server** (`harness/`) that we fully control and that
simulates adversarial behaviors on demand: `429 + Retry-After`, `403` block after N
requests per identity/IP, CAPTCHA/JS-challenge pages, cookie walls, soft-bans (200 + empty),
selector/shape drift, and a happy path. Resilience tests point the collector at the harness
and assert recovery + zero garbage persisted.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| Local adversarial harness (chosen) | Deterministic, CI-safe, drives exact failure modes; agent-verifiable; a portfolio artifact itself | Must build/maintain the mock |
| Test against live sites | "Real" | Non-deterministic, gets banned, flaky, possibly ToS-violating, unbuildable-by-agent |
| Record/replay real traffic | Realistic payloads | Doesn't exercise *adaptive* anti-bot (rotation/backoff) well |

## Consequences
- Positive: the hardest, most valuable behavior becomes deterministically testable; enables
  autonomous agent build+verify; doubles as a demonstrable artifact ("here's my adversary
  and here's my collector beating it").
- Negative: the harness is code to maintain (small, high-leverage).
- Follow-up: pair the harness with fixture payloads (real shapes) for parsing tests.

## Notes
This ADR is what reconciles the two project constraints: *demonstrate adversarial-collection
mastery* AND *be implementable/verifiable by Claude Code alone*. Keep harness scenarios in
sync with the resilience behaviors in docs/04.
