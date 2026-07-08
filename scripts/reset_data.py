"""Wipe all crawled data for a clean slate (switch demo <-> live, or start fresh).

Truncates the data tables (products, price observations, crawl runs, ban events, sources) — the
schema stays; re-seed + crawl to repopulate. Handy to clear the demo before showing the live store
(or vice versa) so the dashboard shows only what you just crawled.
"""

from __future__ import annotations

from sqlalchemy import text

from acquire_intel.storage import get_engine

_TABLES = "ban_events, price_observations, crawl_runs, products, sources"


def main() -> None:
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))
    print(f"reset: truncated {_TABLES}")


if __name__ == "__main__":
    main()
