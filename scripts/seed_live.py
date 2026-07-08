"""Seed the ``live_rest`` source at a real public Shopify store's ``products.json``.

Points the live source at a real store so the app shows **real products and prices** through the
exact same engine the demo uses. Public catalogue data only; the crawl obeys ``robots.txt`` by
default (docs/08). Any store whose ``/products.json`` is open works:

    uv run python scripts/seed_live.py --url https://www.deathwishcoffee.com
    uv run acquire-intel crawl live_rest

Re-run with a different ``--url`` to re-point the same source (idempotent upsert). Prices show in
the store's own currency, so pass ``--currency`` for a non-USD store.
"""

from __future__ import annotations

import argparse

from acquire_intel.storage import Source, SourceRepository, session_scope

_SOURCE_ID = "live_rest"
_DEFAULT_STORE = "https://www.deathwishcoffee.com"  # a public Shopify store, open products.json
_STALE_AFTER_SECONDS = 21_600  # 6h


def seed(base_url: str, currency: str) -> str:
    """Upsert the ``live_rest`` source at ``base_url`` with ``currency``; return the base_url."""
    base_url = base_url.rstrip("/")
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
                    crawl_policy={"default_currency": currency},
                )
            )
        else:
            existing.base_url = base_url
            existing.crawl_policy = {**(existing.crawl_policy or {}), "default_currency": currency}
    return base_url


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed live_rest at a real Shopify store")
    parser.add_argument(
        "--url", default=_DEFAULT_STORE, help=f"store base URL (default: {_DEFAULT_STORE})"
    )
    parser.add_argument(
        "--currency", default="USD", help="ISO-4217 currency for the store (default: USD)"
    )
    args = parser.parse_args()
    base_url = seed(args.url, args.currency)
    print(f"seeded source {_SOURCE_ID!r} -> {base_url}/products.json ({args.currency})")


if __name__ == "__main__":
    main()
