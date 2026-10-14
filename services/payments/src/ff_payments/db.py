"""SQLAlchemy 2 async models. Money is stored as decimal strings (exact, SQLite-safe).

``ledger_entries`` is append-only: the ORM refuses UPDATE and DELETE of its rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, TypeDecorator, event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from ff_payments.dburl import is_sqlite, normalize_database_url


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.astimezone(UTC) if value else None

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


class Base(DeclarativeBase):
    pass


class InvoiceRow(Base):
    __tablename__ = "invoices"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    deal_id: Mapped[str] = mapped_column(String(64), index=True)
    payer_user_id: Mapped[str] = mapped_column(String(64), index=True)
    payee: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(20), index=True)
    status_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    provider: Mapped[str] = mapped_column(String(16))
    provider_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    pay_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pay_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pay_amount: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pay_currency: Mapped[str | None] = mapped_column(String(5), nullable=True)
    memo: Mapped[str] = mapped_column(String(64), unique=True)
    user_memo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tx_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmations: Mapped[int] = mapped_column(Integer, default=0)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class PaymentAttemptRow(Base):
    """One row per provider charge / observation of funds for an invoice."""

    __tablename__ = "payment_attempts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    provider_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # created|confirming|confirmed|failed
    tx_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(5), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class LedgerEntryRow(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (Index("ix_ledger_entries_group_id", "group_id"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(40))
    invoice_id: Mapped[str] = mapped_column(String(40), index=True)
    account: Mapped[str] = mapped_column(String(100))
    direction: Mapped[str] = mapped_column(String(6))
    amount: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(5))
    reason: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class WebhookEventRow(Base):
    """Replay protection: one row per (provider, event_id) ever accepted."""

    __tablename__ = "webhook_events"
    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    invoice_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime())


class OutboxEventRow(Base):
    """Settlement events owed to rfq. Written in the same transaction as the invoice transition."""

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_status_next", "status", "next_attempt_at"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # time-ordered: delivery order per deal
    event_id: Mapped[str] = mapped_column(String(128), unique=True)  # "<invoice_id>:<paid|refunded>"
    deal_id: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10))  # pending | delivered | dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class LedgerImmutable(RuntimeError):
    pass


@event.listens_for(LedgerEntryRow, "before_update")
@event.listens_for(LedgerEntryRow, "before_delete")
def _ledger_is_append_only(*_: Any) -> None:
    raise LedgerImmutable("ledger_entries are append-only")


def make_engine(url: str) -> AsyncEngine:
    url = normalize_database_url(url)
    if ":memory:" in url:
        return create_async_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    if is_sqlite(url):
        return create_async_engine(url)
    return create_async_engine(url, pool_pre_ping=True)
