"""SQLAlchemy 2 async models for the persistent 'native' source. Money is stored as decimal strings."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from .dburl import is_sqlite, normalize_database_url


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.astimezone(UTC) if value else None

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


class Base(DeclarativeBase):
    pass


class NativeListingRow(Base):
    __tablename__ = "native_listings"
    __table_args__ = (
        Index("ix_native_listings_supplier_status", "supplier_id", "status"),
        # public search window: newest published first, optionally per kind (no sort of every published row)
        Index("ix_native_listings_status_published", "status", "published_at"),
        Index("ix_native_listings_status_kind_published", "status", "kind", "published_at"),
        UniqueConstraint("supplier_id", "external_ref", name="uq_native_listings_supplier_ref"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    condition: Mapped[str] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(String(140))
    title_ar: Mapped[str | None] = mapped_column(String(140), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64))
    price_min: Mapped[str] = mapped_column(String(32))
    price_max: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3))
    unit: Mapped[str] = mapped_column(String(24))
    moq: Mapped[int] = mapped_column(Integer)
    incoterm: Mapped[str | None] = mapped_column(String(3), nullable=True)
    unit_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_volume_m3: Mapped[float | None] = mapped_column(Float, nullable=True)
    hs_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    lead_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    images: Mapped[list] = mapped_column(JSON, default=list)
    origin: Mapped[dict] = mapped_column(JSON)
    specs: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # moderation (status hidden / pending_review): who/why, and where to go back to on restore
    moderation_source: Mapped[str | None] = mapped_column(String(8), nullable=True)  # auto | report | admin
    moderation_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    status_before: Mapped[str | None] = mapped_column(String(10), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)  # supplier's own id (bulk import)
    moderated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ListingReportRow(Base):
    """One user report. ``reporter_ref`` is a keyed hash of the reporter's user id: never the id itself."""

    __tablename__ = "listing_reports"
    __table_args__ = (
        UniqueConstraint("listing_id", "reporter_ref", name="uq_listing_reports_listing_reporter"),
        Index("ix_listing_reports_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    listing_id: Mapped[str] = mapped_column(String(16), index=True)
    reporter_ref: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(24))
    details: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(10))  # open | actioned | dismissed
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class PriceObservationRow(Base):
    """One observed price of one listing (min unit price). Bounded per listing; see price_history.py."""

    __tablename__ = "price_observations"
    __table_args__ = (Index("ix_price_observations_listing_time", "listing_id", "observed_at"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(String(64))
    price: Mapped[str] = mapped_column(String(32))  # decimal string
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ListingStatRow(Base):
    """Daily aggregate counter of one listing and metric. No viewer data: only counts (see analytics.py)."""

    __tablename__ = "listing_stats_daily"
    __table_args__ = (Index("ix_listing_stats_daily_day", "day"),)

    listing_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    day: Mapped[date] = mapped_column(Date(), primary_key=True)
    metric: Mapped[str] = mapped_column(String(16), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    uniques: Mapped[int] = mapped_column(Integer, default=0)  # estimate of distinct viewers that day


def make_engine(url: str) -> AsyncEngine:
    url = normalize_database_url(url)
    if ":memory:" in url:
        return create_async_engine(
            url, poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
    if is_sqlite(url):
        return create_async_engine(url)
    return create_async_engine(url, pool_pre_ping=True)
