"""SQLAlchemy 2 async models. Money is stored as decimal strings (exact, SQLite-safe)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    event,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from ff_rfq.dburl import is_sqlite, normalize_database_url


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
    __table_args__ = (Index("ix_requests_owner_created", "owner_id", "created_at"),
                      Index("ix_requests_status_created", "status", "created_at"))


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
    __table_args__ = (Index("ix_deals_buyer_created", "buyer_id", "created_at"),
                      Index("ix_deals_supplier_created", "supplier_user_id", "created_at"))
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
    # per invoice kind: {"commission": {"invoice_id", "status": open|paid|refunded}, "deal_payment": {...}}
    payment_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class DealEventRow(Base):
    """Immutable per-deal audit log (who / when / what). ``event_id`` dedupes payments callbacks."""

    __tablename__ = "deal_events"
    __table_args__ = (UniqueConstraint("deal_id", "seq", name="uq_deal_events_deal_seq"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(64))  # user id, or "system:payments"
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    event_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ReviewRow(Base):
    """One buyer review per deal. ``status`` published|deleted; deleted rows stay for the audit trail."""

    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    deal_id: Mapped[str] = mapped_column(ForeignKey("deals.id"), unique=True)
    buyer_id: Mapped[str] = mapped_column(String(64), index=True)
    supplier_ref: Mapped[str] = mapped_column(String(64), index=True)
    reviewer_display: Mapped[str] = mapped_column(String(64))
    rating: Mapped[int] = mapped_column(Integer)
    quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    communication: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shipping: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), index=True)
    flagged_for_review: Mapped[bool] = mapped_column(Boolean, default=False)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ReviewEventRow(Base):
    """Append-only audit trail (created / edited / deleted / replied / reported) with the prior values."""

    __tablename__ = "review_events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"), index=True)
    action: Mapped[str] = mapped_column(String(12))
    actor_id: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ReviewReportRow(Base):
    __tablename__ = "review_reports"
    __table_args__ = (UniqueConstraint("review_id", "reporter_id", name="uq_review_reports_review_reporter"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"), index=True)
    reporter_id: Mapped[str] = mapped_column(String(64), index=True)
    reason: Mapped[str] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class DealEventImmutable(RuntimeError):
    pass


@event.listens_for(DealEventRow, "before_update")
@event.listens_for(DealEventRow, "before_delete")
def _deal_events_append_only(*_: Any) -> None:
    raise DealEventImmutable("deal_events are append-only")


def make_engine(url: str) -> AsyncEngine:
    url = normalize_database_url(url)
    if ":memory:" in url:
        return create_async_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    if is_sqlite(url):
        return create_async_engine(url)
    return create_async_engine(url, pool_pre_ping=True)
