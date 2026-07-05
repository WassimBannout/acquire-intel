"""SQLAlchemy 2.0 ORM models — the physical schema (ADR-0006, docs/03).

Design invariants encoded here:
- ``price_observations`` is an **append-only** time-series (immutable rows).
- ``products`` is a rebuildable **upsert projection**.
- ``crawl_runs`` + ``ban_events`` form the **collection audit trail**.
- Money is ``NUMERIC`` → :class:`~decimal.Decimal` + ISO-4217 ``currency``, never float.
- All timestamps are timezone-aware UTC.

Enum-like string columns (``status``, ``kind``, ``action_taken``) are validated at the
pydantic boundary (ADR-0008); the DB stores plain strings to keep migrations simple.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base; ``Base.metadata`` is the Alembic ``target_metadata``."""


class Source(Base):
    """A crawl source registry entry (kind + base URL + crawl policy)."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # html | rest | graphql
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    stale_after_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    crawl_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Product(Base):
    """Canonical product projection; one row per (source_id, external_id)."""

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_products_source_external"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)  # {source_id}:{external_id}
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CrawlRun(Base):
    """One collection attempt for a source — the health/audit ledger."""

    __tablename__ = "crawl_runs"
    __table_args__ = (Index("ix_crawl_runs_source_started", "source_id", "started_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # running|success|partial|failed
    items_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ban_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # count
    timings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PriceObservation(Base):
    """Immutable price capture — the append-only time-series (axis: captured_at)."""

    __tablename__ = "price_observations"
    __table_args__ = (
        Index("ix_price_obs_product_captured", "product_id", "captured_at"),
        Index("ix_price_obs_source_captured", "source_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("crawl_runs.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric, nullable=False)  # Decimal, never float
    currency: Mapped[str] = mapped_column(String(3), nullable=False)  # ISO-4217
    in_stock: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BanEvent(Base):
    """One detected block/rate-limit/CAPTCHA/empty response + the action taken."""

    __tablename__ = "ban_events"
    __table_args__ = (
        Index("ix_ban_events_run", "run_id"),
        Index("ix_ban_events_kind_occurred", "kind", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("crawl_runs.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # rate_limited|blocked|captcha|empty
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action_taken: Mapped[str] = mapped_column(String, nullable=False)  # backoff|rotate_*|give_up
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
