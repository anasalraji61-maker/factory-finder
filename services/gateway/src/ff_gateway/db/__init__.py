"""Async SQLAlchemy setup and the users table."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: "usr_" + uuid.uuid4().hex)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(10), default="buyer")
    default_destination: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    supplier_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    # none | pending | verified; only verified claims are forwarded to messaging as X-Supplier-Id
    supplier_claim_status: Mapped[str] = mapped_column(String(10), default="none", server_default="none")
    display_currency: Mapped[str] = mapped_column(String(3), default="USD")
    language: Mapped[str] = mapped_column(String(2), default="ar")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def make_engine(url: str) -> AsyncEngine:
    if ":memory:" in url or url.endswith("sqlite+aiosqlite://"):
        return create_async_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    return create_async_engine(url)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


def _add_missing_columns(sync_conn) -> None:
    """Lightweight migration for dev DBs created before supplier_claim_status existed."""
    from sqlalchemy import inspect

    cols = {c["name"] for c in inspect(sync_conn).get_columns("users")}
    if "supplier_claim_status" not in cols:
        sync_conn.execute(text("ALTER TABLE users ADD COLUMN supplier_claim_status VARCHAR(10) NOT NULL DEFAULT 'none'"))
        # claims made before verification existed are unverified: park them as pending for admin review
        sync_conn.execute(text("UPDATE users SET supplier_claim_status = 'pending' WHERE supplier_id IS NOT NULL"))
