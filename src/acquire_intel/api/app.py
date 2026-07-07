"""Flask application factory (ADR-0007).

Routes stay thin: validate → service → serialize. The base path comes from config
(``API_BASE_PATH``), never hard-coded.
"""

from __future__ import annotations

from flask import Flask

from acquire_intel.acquisition.scheduler import start_scheduler
from acquire_intel.api.admin import admin_bp
from acquire_intel.api.dashboard import dashboard_bp
from acquire_intel.api.deals import deals_bp
from acquire_intel.api.errors import register_error_handlers
from acquire_intel.api.health import health_bp
from acquire_intel.api.monitoring import monitoring_bp
from acquire_intel.api.products import products_bp
from acquire_intel.config import get_settings


def create_app() -> Flask:
    """Build and configure the Flask app."""
    cfg = get_settings()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = cfg.flask_secret_key

    register_error_handlers(app)
    app.register_blueprint(health_bp, url_prefix=cfg.api_base_path)
    app.register_blueprint(monitoring_bp, url_prefix=cfg.api_base_path)
    app.register_blueprint(products_bp, url_prefix=cfg.api_base_path)
    app.register_blueprint(deals_bp, url_prefix=cfg.api_base_path)
    app.register_blueprint(admin_bp, url_prefix=cfg.api_base_path)
    # The human-facing dashboard is served at the site root (the JSON API stays under the
    # configured base path); routes stay thin, rendering Jinja + Chart.js (ADR-0007).
    app.register_blueprint(dashboard_bp)

    # In-process per-source crawl scheduler (opt-in via SCHEDULER_ENABLED); held on the app so
    # its lifecycle follows the process. Disabled by default, so tests/CLI never auto-crawl.
    scheduler = start_scheduler()
    if scheduler is not None:
        app.extensions["scheduler"] = scheduler
    return app
