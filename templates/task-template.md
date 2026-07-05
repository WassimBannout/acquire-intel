# Task <ID> — <short title>

- **Phase / Milestone:** <e.g. Phase 3 / M3>
- **Serves:** <PRD FR ids>
- **Governing specs:** <docs/…, specs/…, ADRs>
- **Owner role:** <acquisition-engineer | antibot-specialist | pipeline-engineer | architect | qa>

## Goal
<One or two sentences: the thin vertical slice this task delivers.>

## Acceptance criteria
- [ ] <objective, testable condition>
- [ ] <objective, testable condition>
- [ ] Invariants honored: never persist blocked/invalid responses; pydantic at boundaries;
      Decimal money+currency; respectful crawling (where applicable).

## Deliverables
- <files/modules to add or change>
- Tests: <unit / integration / harness scenarios> per `docs/06`.

## Verify (the gate — all must pass)
- [ ] ruff + mypy clean
- [ ] unit/integration tests green
- [ ] harness scenarios green (if a resilience task)
- [ ] acceptance criteria met
- [ ] observed running (real crawl/API output pasted)

## Notes
<decisions, risks, or an ADR this may spawn>
