"""Tables (SQLAlchemy Core) and the async engine factory."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ff_feed.dburl import normalize_database_url

metadata = MetaData()


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo on read)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


posts = Table(
    "posts",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("supplier_id", String(64), nullable=False),
    Column("author_user_id", String(128), nullable=False),
    Column("body", Text, nullable=False),
    Column("media", JSON, nullable=False),
    Column("tags", JSON, nullable=False),
    Column("listing_ref", String(64), nullable=True),
    Column("status", String(12), nullable=False),  # published | hidden
    Column("hidden_reason", String(300), nullable=True),
    Column("like_count", Integer, nullable=False, default=0),
    Column("comment_count", Integer, nullable=False, default=0),
    Column("report_count", Integer, nullable=False, default=0),
    Column("score", Integer, nullable=False, default=0),  # like_count + 2 * comment_count
    Column("created_at", UTCDateTime, nullable=False),
    Index("ix_posts_status_created", "status", "created_at", "id"),
    Index("ix_posts_supplier_created", "supplier_id", "created_at", "id"),
    Index("ix_posts_status_score", "status", "score", "created_at", "id"),
)

follows = Table(
    "follows",
    metadata,
    Column("user_id", String(128), primary_key=True),
    Column("supplier_id", String(64), primary_key=True),
    Column("created_at", UTCDateTime, nullable=False),
    Index("ix_follows_supplier", "supplier_id"),
    Index("ix_follows_user_created", "user_id", "created_at", "supplier_id"),
)

likes = Table(
    "likes",
    metadata,
    Column("post_id", String(40), ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", String(128), primary_key=True),
    Column("created_at", UTCDateTime, nullable=False),
    Index("ix_likes_user_post", "user_id", "post_id"),
)

comments = Table(
    "comments",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("post_id", String(40), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", String(128), nullable=False),
    Column("body", Text, nullable=False),
    Column("status", String(12), nullable=False),  # published | hidden
    Column("hidden_reason", String(300), nullable=True),
    Column("report_count", Integer, nullable=False, default=0),
    Column("created_at", UTCDateTime, nullable=False),
    Index("ix_comments_post_created", "post_id", "status", "created_at", "id"),
    Index("ix_comments_status_created", "status", "created_at", "id"),
)

reports = Table(
    "reports",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("target_type", String(8), nullable=False),  # post | comment
    Column("target_id", String(40), nullable=False),
    Column("reporter_id", String(128), nullable=False),
    Column("reason", String(32), nullable=False),
    Column("details", String(300), nullable=True),  # redacted: no links / emails / phones
    Column("created_at", UTCDateTime, nullable=False),
    UniqueConstraint("target_type", "target_id", "reporter_id", name="uq_reports_once"),
    Index("ix_reports_target", "target_type", "target_id", "created_at"),
)

rate_events = Table(
    "rate_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String(128), nullable=False),
    Column("action", String(16), nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    Index("ix_rate_user_action_created", "user_id", "action", "created_at"),
)


def make_engine(url: str) -> AsyncEngine:
    url = normalize_database_url(url)
    opts = {} if url.startswith("sqlite") else {"pool_pre_ping": True}
    return create_async_engine(url, **opts)


def now() -> datetime:
    return datetime.now(UTC)
