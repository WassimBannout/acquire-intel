"""config: typed configuration & the env boundary (pydantic-settings).

All environment access is centralized here so no other module reads ``os.environ``
directly (ADR-0008). Import :func:`get_settings` to obtain validated, process-wide
configuration; it fails fast with :class:`ConfigError` on missing/invalid vars.
"""

from acquire_intel.config.settings import ConfigError, Settings, get_settings

__all__ = ["ConfigError", "Settings", "get_settings"]
