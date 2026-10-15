"""Async SQLAlchemy setup and the users table."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint, false, text
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

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: "usr_" + uuid.uuid4().hex
    )
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(10), default="buyer")
    default_destination: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    supplier_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    # none | pending | verified; only verified claims are forwarded to messaging as X-Supplier-Id
    supplier_claim_status: Mapped[str] = mapped_column(
        String(10), default="none", server_default="none"
    )
    display_currency: Mapped[str] = mapped_column(String(3), default="USD")
    language: Mapped[str] = mapped_column(String(2), default="ar")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    # Account deletion: scheduled_at is set during the optional grace period (login cancels it);
    # deleted_at marks the anonymized tombstone row (the id is kept for referential integrity).
    deletion_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeletionJob(Base):
    """Durable per-service erasure task for a deleted account; retried with backoff until done or dead."""

    __tablename__ = "deletion_jobs"
    __table_args__ = (UniqueConstraint("user_id", "service", name="uq_deletion_jobs_user_service"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    service: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(8), default="pending", index=True)  # pending | done | dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(40), nullable=True)  # short code only, never a body
    supplier_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # verified claim, cleared when done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccountEvent(Base):
    """Append-only audit trail of export / deletion actions. Holds opaque ids and counters, never PII."""

    __tablename__ = "account_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    event: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base):
    """One row per issued refresh token; only the hash of its jti is stored."""

    __tablename__ = "refresh_tokens"

    jti_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    family: Mapped[str] = mapped_column(String(40), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailVerificationToken(Base):
    """Pending email verification; only the SHA-256 of the random token is stored."""

    __tablename__ = "email_verification_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    email: Mapped[str] = mapped_column(String(320))  # address the token proves (stale after an email change)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordResetToken(Base):
    """Pending password reset; only the SHA-256 of the random token is stored."""

    __tablename__ = "password_reset_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def make_engine(url: str) -> AsyncEngine:
    if ":memory:" in url or url.endswith("sqlite+aiosqlite://"):
        return create_async_engine(
            url, poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
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
    if "email_verified" not in cols:
        sync_conn.execute(
            text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT FALSE")
        )
    ts = "TIMESTAMP WITH TIME ZONE" if sync_conn.dialect.name == "postgresql" else "DATETIME"
    for col in ("deletion_scheduled_at", "deleted_at"):
        if col not in cols:
            sync_conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ts} NULL"))
    if "supplier_claim_status" not in cols:
        sync_conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN supplier_claim_status VARCHAR(10) NOT NULL DEFAULT 'none'"
            )
        )
        # claims made before verification existed are unverified: park them as pending for admin review
        sync_conn.execute(
            text("UPDATE users SET supplier_claim_status = 'pending' WHERE supplier_id IS NOT NULL")
        )
