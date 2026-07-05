---
description: Draft a new Architecture Decision Record from the template
---

Create a new ADR for a decision just made (or that needs making).

1. Read `templates/adr-template.md` and the latest number in `docs/adr/` to pick the next
   `NNNN`.
2. Draft `docs/adr/NNNN-<kebab-slug>.md` filling every section: Context, Decision, Options
   considered (pros/cons), Consequences (incl. trade-offs), Notes.
3. Keep it grounded in the project's forces (resilient collection, pluggable sources, never
   cache garbage, verifiable-via-harness, respectful crawling) and reference related
   ADRs/specs.
4. Add a row to the table in `docs/adr/README.md`.

Decision to record: $ARGUMENTS
