"""SQLAlchemy 2 async models (``media_files`` metadata, ``upload_events`` for the hourly quota)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, TypeDecorator, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from ff_media.dburl import is_sqlite, normalize_database_url


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.astimezone(UTC) if value else None

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


class Base(DeclarativeBase):
    pass


class MediaFileRow(Base):
    __tablename__ = "media_files"
    __table_args__ = (UniqueConstraint("owner_id", "sha256", name="uq_media_files_owner_sha256"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    content_type: Mapped[str] = mapped_column(String(32))
    ext: Mapped[str] = mapped_column(String(4))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    widths: Mapped[str] = mapped_column(String(16), default="")  # comma separated variant widths
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class UploadEventRow(Base):
    """One row per upload request that passed auth (valid or not): the rolling-hour quota."""

    __tablename__ = "upload_events"
    __table_args__ = (Index("ix_upload_events_owner_created", "owner_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


def make_engine(url: str) -> AsyncEngine:
    url = normalize_database_url(url)
    if ":memory:" in url:
        return create_async_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    if is_sqlite(url):
        return create_async_engine(url)
    return create_async_engine(url, pool_pre_ping=True)
