"""storage: persistence.

SQLAlchemy 2.0 models, repositories, and Alembic migrations for the append-only
price-history time-series (ADR-0006, docs/03).
"""

from acquire_intel.storage.db import get_engine, new_session, session_scope
from acquire_intel.storage.models import (
    BanEvent,
    Base,
    CrawlRun,
    PriceObservation,
    Product,
    Source,
)
from acquire_intel.storage.repositories import (
    BanEventRepository,
    CrawlRunRepository,
    PriceObservationRepository,
    ProductRepository,
    SourceRepository,
)

__all__ = [
    "BanEvent",
    "BanEventRepository",
    "Base",
    "CrawlRun",
    "CrawlRunRepository",
    "PriceObservation",
    "PriceObservationRepository",
    "Product",
    "ProductRepository",
    "Source",
    "SourceRepository",
    "get_engine",
    "new_session",
    "session_scope",
]
