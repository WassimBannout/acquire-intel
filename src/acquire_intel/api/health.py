"""Liveness endpoint: ``GET /health`` (docs/07 §2, openapi ``getHealth``).

Returns 200 when the process is up and Postgres is reachable, 503 otherwise. A
cheap ``SELECT 1`` is the reachability probe; failures never leak driver detail.
"""

from __future__ import annotations

from flask import Blueprint
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from acquire_intel.storage.db import get_engine

health_bp = Blueprint("health", __name__)


def _database_reachable() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


@health_bp.get("/health")
def health() -> tuple[dict[str, object], int]:
    """Liveness check gated on DB reachability."""
    db_ok = _database_reachable()
    status = 200 if db_ok else 503
    body: dict[str, object] = {
        "status": "ok" if db_ok else "unavailable",
        "checks": {"database": "ok" if db_ok else "unreachable"},
    }
    return body, status
