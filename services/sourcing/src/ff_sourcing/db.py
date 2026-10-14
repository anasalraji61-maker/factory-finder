"""SQLAlchemy 2 async models for the persistent 'native' source. Money is stored as decimal strings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text, TypeDecorator
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
    __table_args__ = (Index("ix_native_listings_supplier_status", "supplier_id", "status"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(10), index=True)
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


def make_engine(url: str) -> AsyncEngine:
    url = normalize_database_url(url)
    if ":memory:" in url:
        return create_async_engine(
            url, poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
    if is_sqlite(url):
        return create_async_engine(url)
    return create_async_engine(url, pool_pre_ping=True)
