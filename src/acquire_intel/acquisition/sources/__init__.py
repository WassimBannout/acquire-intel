"""Pluggable ``SourceExtractor`` implementations — one module per source (ADR-0003).

Each source of kind ``html`` | ``rest`` | ``graphql`` lives here as a single module and is
registered in ``acquisition/registry.py``. Extractors own only source-specific fetch/parse;
proxies, throttling, retries, validation, and storage are shared layers.
"""
