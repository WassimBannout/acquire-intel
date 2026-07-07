"""Seed a demo ``demo_rest`` source pointed at the adversarial harness (T4.6).

The crawl engine resolves a source's ``base_url`` / currency / freshness from the ``sources``
registry table (T1.7), so a fresh clone has nothing to crawl until a row exists. This dev-only
script registers (or re-points) the ``demo_rest`` source at a chosen harness scenario so the
5-minute demo in the README works end to end:

    uv run python -m harness.server --block-after 1        # terminal 1 (the adversary)
    uv run python scripts/demo_seed.py --scenario block_after_n
    uv run acquire-intel crawl demo_rest

It is **not** shipped in the wheel and never touches a real target — only the local harness. Run it
again with a different ``--scenario`` to re-point the same source (idempotent upsert).
"""

from __future__ import annotations

import argparse

from acquire_intel.storage import Source, SourceRepository, session_scope

# Only scenarios the REST extractor can walk (``GET /<scenario>/products.json``). ``happy`` shows
# the clean pipeline; the rest exercise the resilience layer (recover, or record-and-drop garbage).
_SCENARIOS = (
    "happy",
    "rate_limited",
    "block_after_n",
    "captcha",
    "cookie_wall",
    "soft_ban",
    "drift",
)

_SOURCE_ID = "demo_rest"
_STALE_AFTER_SECONDS = 21_600  # 6h; matches the resilience integration fixtures


def seed(harness_base: str, scenario: str) -> str:
    """Upsert the ``demo_rest`` source at ``{harness_base}/{scenario}``; return its base_url."""
    base_url = f"{harness_base.rstrip('/')}/{scenario}"
    with session_scope() as session:
        repo = SourceRepository(session)
        existing = repo.get(_SOURCE_ID)
        if existing is None:
            repo.add(
                Source(
                    id=_SOURCE_ID,
                    kind="rest",
                    base_url=base_url,
                    stale_after_seconds=_STALE_AFTER_SECONDS,
                    crawl_policy={"default_currency": "USD"},
                )
            )
        else:
            existing.base_url = base_url  # re-point the same source at a new scenario
    return base_url


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the demo_rest source against the harness")
    parser.add_argument(
        "--scenario",
        choices=_SCENARIOS,
        default="happy",
        help="harness scenario to point demo_rest at (default: happy)",
    )
    parser.add_argument(
        "--harness-base",
        default="http://127.0.0.1:8080",
        help="base URL of the running harness (default: http://127.0.0.1:8080)",
    )
    args = parser.parse_args()
    base_url = seed(args.harness_base, args.scenario)
    print(f"seeded source {_SOURCE_ID!r} -> {base_url}")


if __name__ == "__main__":
    main()
