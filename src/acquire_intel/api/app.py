"""Flask application factory (ADR-0007).

Routes stay thin: validate → service → serialize. The base path comes from config
(``API_BASE_PATH``), never hard-coded.
"""

from __future__ import annotations

from flask import Flask

from acquire_intel.api.errors import register_error_handlers
from acquire_intel.api.health import health_bp
from acquire_intel.config import get_settings


def create_app() -> Flask:
    """Build and configure the Flask app."""
    cfg = get_settings()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = cfg.flask_secret_key

    register_error_handlers(app)
    app.register_blueprint(health_bp, url_prefix=cfg.api_base_path)
    return app
