"""The single environment boundary (ADR-0008).

All environment access in AcquireIntel goes through :func:`get_settings`. No other
module reads ``os.environ`` — this keeps configuration typed, validated once, and
fail-fast: a missing or malformed required variable raises :class:`ConfigError`
with a clear message at startup rather than surfacing as a mysterious failure deep
in a crawl.

Variable catalogue and defaults live in ``docs/05-tech-stack.md`` and are mirrored,
key-for-key, in ``.env.example``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when environment configuration is missing or invalid.

    Carries a human-readable, multi-line message safe to print at startup. It
    never contains secret *values* — only the offending variable names and the
    validation reason.
    """


class Settings(BaseSettings):
    """Typed application configuration, parsed from the environment / ``.env``.

    Field names map to ``SCREAMING_SNAKE_CASE`` env vars (case-insensitive).
    Fields without a default are **required**; booting without them fails fast.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- required (no safe default; environment-specific or secret) ----------
    database_url: str
    """SQLAlchemy URL, e.g. ``postgresql+psycopg://user:pass@host:5432/db``."""

    flask_secret_key: str
    """Flask session signing key (secret)."""

    admin_token: str
    """Bearer token gating the on-demand/admin crawl trigger (secret)."""

    # --- api -----------------------------------------------------------------
    api_base_path: str = "/api/v1"

    # --- acquisition (respectful-crawling posture; docs/08) ------------------
    contact_user_agent: str = "AcquireIntelBot/0.1 (+contact@example.com)"
    robotstxt_obey: bool = True
    proxy_pool: str = ""
    """Comma-separated proxy URLs; empty means crawl directly. See ``proxy_urls``."""
    default_download_delay: float = 1.0
    autothrottle_enabled: bool = True

    # --- harness (tests only) ------------------------------------------------
    harness_base_url: str = "http://localhost:8999"

    @property
    def proxy_urls(self) -> list[str]:
        """``PROXY_POOL`` parsed into a clean list (empty list = direct)."""
        return [p.strip() for p in self.proxy_pool.split(",") if p.strip()]


def _format_validation_error(exc: ValidationError) -> str:
    """Turn a pydantic ValidationError into a concise, value-free message."""
    lines = ["Configuration error — invalid or missing environment variables:"]
    for err in exc.errors():
        # loc is the field name; map back to the env var name we document.
        field = ".".join(str(part) for part in err["loc"]) or "<root>"
        env_name = field.upper()
        lines.append(f"  - {env_name}: {err['msg']}")
    lines.append("Set them in the environment or a .env file (see .env.example).")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, parsed and validated exactly once.

    Raises:
        ConfigError: if any required variable is missing or a value is invalid.
    """
    try:
        return Settings()
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc
