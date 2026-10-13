"""SQLAlchemy 2 async models. Money is stored as decimal strings (exact, SQLite-safe)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, TypeDecorator
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.astimezone(UTC) if value else None

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


class Base(DeclarativeBase):
    pass


class RequestRow(Base):
    __tablename__ = "requests"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[str] = mapped_column(String(32))
    unit: Mapped[str] = mapped_column(String(24))
    condition: Mapped[str] = mapped_column(String(8))
    target_amount: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    destination: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    visibility: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class OfferRow(Base):
    __tablename__ = "offers"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True)
    supplier_user_id: Mapped[str] = mapped_column(String(64), index=True)
    supplier_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supplier_name: Mapped[str] = mapped_column(String(200))
    price_amount: Mapped[str] = mapped_column(String(32))
    price_currency: Mapped[str] = mapped_column(String(3))
    moq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    incoterm: Mapped[str | None] = mapped_column(String(3), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(12), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class DealRow(Base):
    __tablename__ = "deals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(40), unique=True)
    offer_id: Mapped[str] = mapped_column(String(40), unique=True)
    buyer_id: Mapped[str] = mapped_column(String(64), index=True)
    supplier_user_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3))
    subtotal: Mapped[str] = mapped_column(String(32))
    commission_rate: Mapped[str] = mapped_column(String(10))
    commission_amount: Mapped[str] = mapped_column(String(32))
    min_fee_applied: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


def make_engine(url: str) -> AsyncEngine:
    if ":memory:" in url:
        return create_async_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    return create_async_engine(url)
