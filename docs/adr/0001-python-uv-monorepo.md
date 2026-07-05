# ADR-0001: Python 3.12 + uv, single package (src layout)

- **Status:** Accepted
- **Date:** 2026-07-05
- **Deciders:** Architect, Senior Developer
- **Related:** docs/05-tech-stack.md, ADR-0002

## Context
The target role is Python-centric (Scrapy/Playwright). We need a reproducible, typed,
agent-navigable project with fast setup and clean module boundaries (acquisition,
resilience, pipeline, storage, api, monitoring).

## Decision
We will build a single **Python 3.12+** package under a **`src/` layout**, managed with
**uv** and `pyproject.toml`, with internal modules per concern. Ruff (lint+format) and mypy
(types) are mandatory.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| uv + single src package (chosen) | Fast, reproducible, simple, one venv; easy for agents | uv newer than pip/Poetry (well-supported) |
| Poetry | Popular, mature | Slower; heavier resolver |
| Multiple packages / monorepo tool | Strong isolation | Overkill at this size |

## Consequences
- Positive: `uv sync` reproduces the env; modules give structure without distribution
  overhead; mypy/ruff enforce quality for AI edits.
- Negative: contributors must know uv.
- Follow-up: commit `uv.lock`; root scripts/CLI entrypoint (`acquire-intel`).

## Notes
Strict typing + ruff are non-negotiable — the primary defense against AI-introduced drift
and untyped-boundary bugs.
