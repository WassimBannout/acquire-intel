"""Live Shopify-store REST extractor (``kind="rest"``).

Same acquisition logic as :class:`~acquire_intel.acquisition.sources.demo_rest.DemoRestExtractor`
— a paginated Shopify ``products.json`` walk — but a **distinct source id** (``live_rest``) so a
real store's catalogue persists and displays separately from the demo/harness data. The canonical
product id is ``{source}:{external_id}`` keyed on the extractor's ``id`` (pipeline), so reusing the
demo id would file real products under ``demo_rest`` and mix the two.

The concrete store is supplied by config (the ``sources`` row's ``base_url`` + currency), never
hardcoded, so ``live_rest`` can point at **any** public Shopify store that serves an open
``products.json``. Public catalogue data only, ``robots.txt`` obeyed by default (docs/08).
"""

from __future__ import annotations

from acquire_intel.acquisition.sources.demo_rest import DemoRestExtractor


class LiveRestExtractor(DemoRestExtractor):
    """A real live Shopify store, crawled through the same ``products.json`` path as the demo."""

    id = "live_rest"
    name = "live_rest"
