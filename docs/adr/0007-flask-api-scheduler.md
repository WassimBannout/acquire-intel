# ADR-0007: Flask API + Jinja/Chart.js dashboard; APScheduler

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Senior Developer, Product Manager
- **Related:** docs/05-tech-stack.md, PRD FR-13/FR-14/FR-15

## Context
We need a thin read/serve surface (products, price history, deals, health) and a light
dashboard, plus scheduled and on-demand crawls. For a data-acquisition project the web tier
is minor; the weight is in acquisition.

## Decision
We will serve the API with **Flask** (pydantic for serialization/validation), render a light
dashboard with **Jinja + Chart.js**, and schedule crawls with **APScheduler** in-process
(also triggerable via CLI and a token-gated `POST /admin/crawl`).

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| Flask + Jinja/Chart.js + APScheduler (chosen) | Simple, widely known, role-appropriate (web is minor); user preference | Sync framework (fine — crawling is separate) |
| FastAPI | Async, auto-OpenAPI | Async unneeded here; user prefers Flask |
| SPA (React) frontend | Rich UX | Overkill; distracts from the acquisition focus |
| External cron/queue scheduler | Scales | Extra infra; APScheduler is enough for v1 |

## Consequences
- Positive: minimal surface to build/test; pydantic keeps validation rigorous regardless of
  framework; dashboard shows price history + crawler health.
- Negative: single-process scheduler (acceptable v1; can externalize later).
- Follow-up: the crawl orchestration must be callable by APScheduler, CLI, and HTTP alike.

## Notes
Keep routes thin: validate → service → serialize. No business logic in views. Never hardcode
targets/DB URLs — everything via `config`.
