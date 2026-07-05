---
description: Start the next unchecked backlog task the AI-native way (read specs → prompt → verify)
---

Begin the next unchecked task in `plan/backlog.md`, following `plan/execution-playbook.md`.

In order:
1. Identify the top `[ ]` task in the current phase. State its id, goal, and acceptance
   criteria.
2. Read every spec/ADR it references (PRD FRs, `docs/`, `specs/`; esp. `docs/04` for
   resilience tasks). Summarize the constraints before coding.
3. Open the matching `prompts/phase-*` section for this task id and follow it.
4. Implement the vertical slice, conforming to the specs (spec-first if behavior changes).
5. Run the verification gate (`docs/06` §5): ruff + mypy, unit/integration tests, harness
   scenarios (for resilience tasks), and a real run/crawl. Not done until all pass and
   acceptance criteria are met.
6. If a load-bearing decision was made, write an ADR from `templates/adr-template.md`.
7. Check the task off in `plan/backlog.md` and update the "Current status" line in `CLAUDE.md`.

$ARGUMENTS
