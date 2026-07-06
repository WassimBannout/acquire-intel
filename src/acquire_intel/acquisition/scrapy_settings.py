"""Build Scrapy settings from the app config boundary (ADR-0002).

Crawl politeness (user-agent, robots obedience, delay, autothrottle) is derived
from :func:`~acquire_intel.config.get_settings` — never hard-coded — so the
respectful-crawling posture (docs/08) is configured in one place.
"""

from __future__ import annotations

from scrapy.settings import Settings

from acquire_intel.config import get_settings


def build_scrapy_settings() -> Settings:
    """Return Scrapy ``Settings`` seeded from environment-backed app config."""
    cfg = get_settings()
    settings = Settings()
    settings.setdict(
        {
            "BOT_NAME": "acquire_intel",
            "USER_AGENT": cfg.contact_user_agent,
            "ROBOTSTXT_OBEY": cfg.robotstxt_obey,
            "DOWNLOAD_DELAY": cfg.default_download_delay,
            "AUTOTHROTTLE_ENABLED": cfg.autothrottle_enabled,
            "TELNETCONSOLE_ENABLED": False,
            "LOG_LEVEL": "INFO",
            # Validate → normalize → dedup, then persist every surviving item (T1.4 → T1.7).
            "ITEM_PIPELINES": {
                "acquire_intel.pipeline.item_pipeline.NormalizePipeline": 300,
                "acquire_intel.pipeline.persistence.PersistencePipeline": 400,
            },
        },
        priority="project",
    )
    return settings
