# Pull Request — <task id>: <short title>

## What & why
<What this change does and which backlog task / PRD FR it serves.>

## Specs honored
- Conforms to: <specs/openapi.yaml, specs/extractor-interface.md, data-contracts, ADRs>
- Behavior change? <If yes, link the spec/doc updated first and any new ADR.>

## How it was verified (docs/06 §5)
- [ ] ruff + mypy clean
- [ ] unit/integration tests green (list key tests)
- [ ] harness scenarios green (if resilience) — list scenarios
- [ ] acceptance criteria met (list)
- [ ] observed running — paste real output (a crawl's recovery/ban events + DB rows, or an
      API response with freshness)

## Invariants check
- [ ] No secret/proxy cred added; config via env only
- [ ] No blocked/invalid response is persisted (detect → record → recover)
- [ ] All boundaries pydantic-validated; upstream shape not trusted
- [ ] Money is Decimal + currency; timestamps UTC
- [ ] Respectful crawling: robots-aware, throttled, honest UA (where applicable)

## Notes / follow-ups
<anything reviewers should know; deferred items as new backlog tasks>
