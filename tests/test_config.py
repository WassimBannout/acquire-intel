"""Tests for the env boundary (T0.2, ADR-0008).

Proves fail-fast on missing required vars and correct parsing of a valid env.
Each test builds ``Settings`` in isolation via ``_env`` and calls
``get_settings.cache_clear()`` so the process-wide lru_cache never leaks between
cases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from acquire_intel.config import ConfigError, Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

REQUIRED = {
    "DATABASE_URL": "postgresql+psycopg://acquire:acquire@localhost:5432/acquire",
    "FLASK_SECRET_KEY": "dev-secret",
    "ADMIN_TOKEN": "dev-token",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Isolate settings: clear known vars, disable .env discovery, reset the cache."""
    for key in (*REQUIRED, "API_BASE_PATH", "PROXY_POOL", "ROBOTSTXT_OBEY"):
        monkeypatch.delenv(key, raising=False)
    # Point env_file at a nonexistent path so a real .env cannot bleed into tests.
    monkeypatch.setitem(Settings.model_config, "env_file", str(tmp_path / "absent.env"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_missing_required_var_fails_fast(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # Provide all but DATABASE_URL.
    monkeypatch.setenv("FLASK_SECRET_KEY", REQUIRED["FLASK_SECRET_KEY"])
    monkeypatch.setenv("ADMIN_TOKEN", REQUIRED["ADMIN_TOKEN"])

    with pytest.raises(ConfigError) as exc:
        get_settings()

    message = str(exc.value)
    assert "DATABASE_URL" in message
    assert ".env.example" in message
    # The error must not leak the secret values we did set.
    assert REQUIRED["FLASK_SECRET_KEY"] not in message


def test_valid_env_loads_with_defaults(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)

    settings = get_settings()

    assert settings.database_url == REQUIRED["DATABASE_URL"]
    assert settings.api_base_path == "/api/v1"  # default applied
    assert settings.robotstxt_obey is True  # default applied
    assert settings.proxy_urls == []  # empty pool = direct


def test_get_settings_is_cached(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    assert get_settings() is get_settings()  # parsed exactly once


def test_proxy_pool_parses_to_list(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PROXY_POOL", "http://a:8000, http://b:8000 ,")

    assert get_settings().proxy_urls == ["http://a:8000", "http://b:8000"]
