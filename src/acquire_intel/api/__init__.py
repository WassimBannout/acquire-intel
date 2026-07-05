"""api: the Flask API + light dashboard.

Serves acquired product & price data with pydantic serialization (ADR-0007).
``create_app`` is the application factory (also discovered by ``flask --app
acquire_intel.api``).
"""

from acquire_intel.api.app import create_app

__all__ = ["create_app"]
