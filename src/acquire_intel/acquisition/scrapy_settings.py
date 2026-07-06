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
            "TELNETCONSOLE_ENABLED": False,
            "LOG_LEVEL": "INFO",
            # Adaptive throttling + per-domain caps (T3.3, docs/04 §2.3): politeness is the
            # first-line anti-ban tool — crawl slowly and concurrently within limits.
            "AUTOTHROTTLE_ENABLED": cfg.autothrottle_enabled,
            "AUTOTHROTTLE_START_DELAY": cfg.default_download_delay,
            "AUTOTHROTTLE_MAX_DELAY": cfg.autothrottle_max_delay,
            "AUTOTHROTTLE_TARGET_CONCURRENCY": cfg.autothrottle_target_concurrency,
            "CONCURRENT_REQUESTS_PER_DOMAIN": cfg.concurrent_requests_per_domain,
            # BackoffRetryMiddleware owns 429/503 (Retry-After-aware) — drop them from the
            # built-in retrier so there is a single backoff owner (T3.3, docs/04 §2.4).
            "RETRY_HTTP_CODES": [500, 502, 504, 522, 524, 408],
            # Resilience knobs read by our middlewares' ``from_crawler``.
            "ACQUIRE_BACKOFF_MAX_RETRIES": cfg.backoff_max_retries,
            "ACQUIRE_BACKOFF_BASE_DELAY": cfg.backoff_base_delay,
            "ACQUIRE_BACKOFF_MAX_DELAY": cfg.backoff_max_delay,
            "ACQUIRE_CIRCUIT_FAILURE_THRESHOLD": cfg.circuit_failure_threshold,
            "ACQUIRE_CIRCUIT_COOLDOWN_SECONDS": cfg.circuit_cooldown_seconds,
            # Playwright for JS-rendered `html` sources (ADR-0002). The handler delegates
            # non-`playwright` requests to the default downloader, so REST/GraphQL are
            # unaffected and no browser launches unless a request opts in via meta.
            "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
            "DOWNLOAD_HANDLERS": {
                "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
                "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            },
            "PLAYWRIGHT_BROWSER_TYPE": "chromium",
            "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
            # Resilience downloader middlewares (T3.2/T3.3, docs/04 sec 2.4-2.5). All sit below
            # HttpCompression (590) / Redirect (600) so they see the final, decompressed body.
            # process_response runs high-to-low: backoff (recover 429/503) -> circuit (record
            # blocks) -> ban gate (record + drop). Only survivors of all three reach a spider.
            "DOWNLOADER_MIDDLEWARES": {
                "acquire_intel.resilience.middleware.BackoffRetryMiddleware": 585,
                "acquire_intel.resilience.middleware.CircuitBreakerMiddleware": 583,
                "acquire_intel.resilience.middleware.BanDetectionMiddleware": 581,
            },
            # Validate → normalize → dedup, then persist every surviving item (T1.4 → T1.7).
            "ITEM_PIPELINES": {
                "acquire_intel.pipeline.item_pipeline.NormalizePipeline": 300,
                "acquire_intel.pipeline.persistence.PersistencePipeline": 400,
            },
        },
        priority="project",
    )
    return settings
