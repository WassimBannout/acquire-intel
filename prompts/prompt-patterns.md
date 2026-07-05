# Prompt Patterns

Reusable scaffolds for prompting Claude Code here. The difference between AI-native
engineering and vibe coding: **every prompt carries intent, the governing spec, and the
verification bar** — and for anti-bot work, the harness scenario it must pass.

## The canonical task prompt (shape for every task)

```
Task <ID> from plan/backlog.md.

Context to read first:
- <the specs/ADRs the task references, by path>   # e.g. docs/04, specs/extractor-interface.md

Goal:
- <one or two sentences: the vertical slice to deliver>

Constraints (must hold):
- Conform to <spec paths>. If a spec is wrong, propose an ADR first.
- <project invariants: never persist blocked/invalid responses; pydantic at boundaries;
  Decimal money+currency; env-only secrets; respectful crawling; resilience proven via harness>

Deliverables:
- <files/modules to create or change>
- Tests: <unit / integration / harness scenarios> per docs/06.

Verification (do all before reporting done):
- ruff + mypy clean
- unit/integration tests green
- (resilience tasks) the relevant harness scenarios green
- acceptance criteria in the backlog met
- run it and show real behavior (a crawl producing rows / an API response / harness recovery),
  not just tests

Report: what changed, the test/harness output, and the observed run. Note any decision that
needs an ADR.
```

## Why each part matters
- **Read-first list** grounds the agent in the contract so it conforms instead of inventing.
- **Constraints** restate the invariants that keep the collector correct and respectful.
- **Verification block** makes "done" objective and observable — and for anti-bot code, the
  harness is what proves it works without a live hostile site.

## Micro-patterns

**Spec-first change**
> "Before coding: update `<spec>` to reflect `<new behavior>`, show the diff, then implement
> to match."

**Golden-fixture extractor test**
> "Add a checked-in fixture of a real `<REST/GraphQL/HTML>` payload under
> `tests/fixtures/<id>/`, plus expected normalized output. Assert parse→RawProduct matches.
> Add a malformed/blocked fixture that must yield nothing (no junk)."

**Harness-driven resilience test**
> "Configure the adversarial harness for `<scenario>` (e.g. 403 after 5 req/identity). Run the
> collector against it. Assert: identity/proxy rotated, BanEvent recorded with the right kind,
> eventual success, and ZERO blocked responses persisted."

**Refuse-to-guess**
> "If `<detail>` is ambiguous against the specs, stop and ask. Do not invent a schema field
> not in the pydantic models / specs."

**Verify by observing**
> "Run the affected flow (`<how>` — a crawl against the harness, or curl the endpoint) and
> paste the actual output. A green test is necessary but not sufficient."

**Decision → ADR**
> "This required choosing `<X over Y>`. Write `docs/adr/<n>-<slug>.md` from the template
> before committing."

## Anti-patterns (never send these)
- ❌ "Build the scraper." (No slice, no spec, no bar.)
- ❌ "Make anti-bot work." (Which scenario? Assert what? Use the harness.)
- ❌ "Test it against <real site>." (Non-deterministic, may ban CI, possibly ToS-violating.)
- ❌ "Store the response, validate later." (Validate/gate before persist.)
- ❌ "Hardcode the proxy/target/DB URL." (Config + env.)

## Long-session hygiene
- Re-anchor after context churn: "Re-read CLAUDE.md and the current task's specs before
  continuing."
- Keep the agent to one task; redirect drift to the backlog item.
- On task completion, update `plan/backlog.md` and the CLAUDE.md status line so the next
  session resumes cleanly.
