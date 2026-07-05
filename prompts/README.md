# Prompt Packs

Version-controlled, spec-referencing prompts for building AcquireIntel. **Do not free-hand
prompts** — edit these so intent stays in git and every session prompts consistently.

## How to use
1. Find the phase file matching your current backlog phase.
2. Locate the section for your task id (e.g. `T3.2`).
3. Copy the prompt, fill `<blanks>`, send it to Claude Code.
4. Enforce the verification block (incl. the adversarial harness for resilience tasks) before
   checking the task off.

## Files
| File | Covers |
|------|--------|
| `prompt-patterns.md` | Reusable prompt scaffolds, the spec-reference habit, anti-patterns |
| `phase-0-bootstrap.md` | uv project, config, Docker/Postgres, Scrapy skeleton, Flask health, CI |
| `phase-1-first-source.md` | Extractor contract, REST extractor, pipeline, persistence, API |
| `phase-2-rest-graphql.md` | HTML (Playwright) + GraphQL extractors under one contract |
| `phase-3-antibot-resilience.md` | The centerpiece: harness, ban detection, throttle/backoff, proxies/identity, quality gates |
| `phase-4-intelligence-hardening.md` | Deals, drift detection, dashboard, health/metrics, scheduler, demo/CI |

## The one rule
Every prompt **names the specs it must conform to** and **states the verification bar**
(including harness scenarios for anti-bot work). A prompt without those two is a vibe-coding
prompt — rewrite it.
