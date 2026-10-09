"""Table definitions (SQLAlchemy Core). Created on startup in dev; Alembic later."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Dialect,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every backend (SQLite has no native tz support)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        value = value.astimezone(UTC)
        return value if dialect.name == "postgresql" else value.replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


JSONType = JSON().with_variant(JSONB(), "postgresql")

ID_LENGTH = 40  # "conv_" / "msg_" + 26-char ULID
USER_ID_LENGTH = 64
REF_LENGTH = 128

conversations = Table(
    "conversations",
    metadata,
    Column("id", String(ID_LENGTH), primary_key=True),
    # sha256(sorted participant ids + context); enforces idempotent creation.
    Column("dedupe_key", String(64), nullable=False, unique=True),
    Column("context_type", String(16), nullable=True),
    Column("context_ref_id", String(REF_LENGTH), nullable=True),
    Column("title", String(255), nullable=True),
    Column("created_by", String(USER_ID_LENGTH), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    # Highest message sequence number; incremented atomically (row lock) for every message.
    Column("last_seq", Integer, nullable=False, default=0),
    Column("last_message_id", String(ID_LENGTH), nullable=True),
    Column("last_message_type", String(16), nullable=True),
    Column("last_message_sender_id", String(USER_ID_LENGTH), nullable=True),
    Column("last_message_preview", String(600), nullable=True),
    Column("last_message_event", String(64), nullable=True),
    Column("last_message_flagged", Boolean, nullable=False, default=False),
    Column("last_message_at", UTCDateTime(), nullable=True),
    Index(None, "context_type", "context_ref_id"),
)

conversation_participants = Table(
    "conversation_participants",
    metadata,
    Column(
        "conversation_id",
        String(ID_LENGTH),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("user_id", String(USER_ID_LENGTH), primary_key=True),
    Column("position", Integer, nullable=False),
    Column("role", String(16), nullable=False),
    Column("joined_at", UTCDateTime(), nullable=False),
    # Denormalised copy of conversations.updated_at -> ordered index scan per user.
    Column("activity_at", UTCDateTime(), nullable=False),
    Column("last_read_seq", Integer, nullable=False, default=0),
    Column("last_read_message_id", String(ID_LENGTH), nullable=True),
    Column("last_read_at", UTCDateTime(), nullable=True),
    Column("unread_count", Integer, nullable=False, default=0),
    Index(None, "user_id", "activity_at", "conversation_id"),
)

messages = Table(
    "messages",
    metadata,
    Column("id", String(ID_LENGTH), primary_key=True),
    Column(
        "conversation_id",
        String(ID_LENGTH),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("seq", Integer, nullable=False),
    Column("sender_id", String(USER_ID_LENGTH), nullable=True),
    Column("type", String(16), nullable=False),
    Column("text", Text, nullable=True),
    Column("attachment_url", String(2048), nullable=True),
    Column("attachment_mime", String(127), nullable=True),
    Column("attachment_size", BigInteger, nullable=True),
    Column("attachment_name", String(255), nullable=True),
    Column("offer_id", String(REF_LENGTH), nullable=True),
    Column("offer_request_id", String(REF_LENGTH), nullable=True),
    Column("event", String(64), nullable=True),
    Column("event_data", JSONType, nullable=True),
    Column("flags", JSONType, nullable=False, default=list),
    Column("client_message_id", String(64), nullable=True),
    # "u:<sender>/<client_message_id>" or "s:/<idempotency_key>"; NULLs never collide.
    Column("dedupe_key", String(256), nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    UniqueConstraint("conversation_id", "seq"),
    UniqueConstraint("conversation_id", "dedupe_key"),
)
