"""config: typed configuration & the env boundary (pydantic-settings).

All environment access is centralized here so no other module reads ``os.environ``
directly (ADR-0008).
"""
