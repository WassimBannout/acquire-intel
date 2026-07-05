---
description: Run the verification gate for the current change before calling it done
---

Verify the current change against `docs/06-testing-strategy.md` §5. Report PASS/FAIL per
criterion; do not soften a failure.

Check, in order, stopping "done" if any fails:
1. **Lint/format** — `uv run ruff check .` clean.
2. **Types** — `uv run mypy src` clean.
3. **Tests** — relevant `uv run pytest` green. For extractors, confirm valid + malformed
   fixtures. For resilience tasks, confirm the **harness scenarios** for this task pass and
   that **zero blocked/invalid responses are persisted**.
4. **Acceptance criteria** — restate the backlog task's criteria; confirm each.
5. **Observed running** — exercise the real interface (run a crawl against the harness and
   show recovery/ban events + DB rows, or curl the endpoint and show the response with
   freshness) and paste the actual output.

If anything fails, name the specific failing criterion and what's needed to fix it.

$ARGUMENTS
