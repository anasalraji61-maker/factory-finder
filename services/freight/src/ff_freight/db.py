"""Tables (SQLAlchemy Core) and the async engine factory.

Money, weights and volumes are stored as exact decimal *strings* (never floats).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Column,
    Date,
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

from ff_freight.dburl import normalize_database_url

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


# A forwarder application (claim): a user asks to become a verified forwarder.
applications = Table(
    "applications",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(128), nullable=False),
    Column("company_name", String(120), nullable=False),
    Column("country_code", String(2), nullable=False),
    Column("description", Text, nullable=True),
    Column("lanes", JSON, nullable=False),  # [[origin, destination], ...] ISO-2 or "*"
    Column("modes", String(40), nullable=False),  # ",sea,air,"
    Column("incoterms", String(80), nullable=False),  # ",FOB,CIF,"
    Column("certifications", JSON, nullable=False),
    Column("status", String(10), nullable=False),  # pending | approved | rejected
    Column("review_note", String(300), nullable=True),
    Column("forwarder_id", String(40), nullable=True),
    Column("created_at", UTCDateTime, nullable=False),
    Column("reviewed_at", UTCDateTime, nullable=True),
    Index("ix_applications_user_created", "user_id", "created_at", "id"),
    Index("ix_applications_status_created", "status", "created_at", "id"),
)

forwarders = Table(
    "forwarders",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("user_id", String(128), nullable=False),
    Column("company_name", String(120), nullable=False),
    Column("country_code", String(2), nullable=False),
    Column("description", Text, nullable=True),
    Column("modes", String(40), nullable=False),
    Column("incoterms", String(80), nullable=False),
    Column("certifications", JSON, nullable=False),
    Column("status", String(10), nullable=False),  # active | suspended
    Column("status_reason", String(300), nullable=True),
    Column("rating_sum", Integer, nullable=False, default=0),
    Column("rating_count", Integer, nullable=False, default=0),
    Column("completed_count", Integer, nullable=False, default=0),
    Column("verified_at", UTCDateTime, nullable=False),
    Column("created_at", UTCDateTime, nullable=False),
    UniqueConstraint("user_id", name="uq_forwarders_user"),
    Index("ix_forwarders_status_created", "status", "created_at", "id"),
)

forwarder_lanes = Table(
    "forwarder_lanes",
    metadata,
    Column("forwarder_id", String(40), ForeignKey("forwarders.id", ondelete="CASCADE"), primary_key=True),
    Column("origin_country", String(2), primary_key=True),  # ISO-2 or "*"
    Column("destination_country", String(2), primary_key=True),
    Index("ix_lanes_route", "origin_country", "destination_country", "forwarder_id"),
)

shipment_requests = Table(
    "shipment_requests",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("buyer_id", String(128), nullable=False),
    Column("origin_country", String(2), nullable=False),
    Column("origin_place", String(80), nullable=False),
    Column("destination_country", String(2), nullable=False),
    Column("destination_place", String(80), nullable=False),
    Column("cargo_description", Text, nullable=False),
    Column("hs_code", String(10), nullable=True),
    Column("weight_kg", String(24), nullable=True),
    Column("volume_cbm", String(24), nullable=True),
    Column("mode", String(8), nullable=False),  # sea | air | road | rail
    Column("container_type", String(12), nullable=True),
    Column("container_count", Integer, nullable=True),
    Column("incoterm", String(3), nullable=False),
    Column("ready_date", Date, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("landed_cost_ref", String(64), nullable=True),
    Column("status", String(10), nullable=False),  # open | awarded | closed | expired
    Column("visibility", String(8), nullable=False),  # visible | hidden (moderation)
    Column("hidden_reason", String(300), nullable=True),
    Column("awarded_quote_id", String(40), nullable=True),
    Column("awarded_forwarder_id", String(40), nullable=True),
    Column("quote_count", Integer, nullable=False, default=0),
    Column("report_count", Integer, nullable=False, default=0),
    Column("expires_at", UTCDateTime, nullable=False),
    Column("awarded_at", UTCDateTime, nullable=True),
    Column("closed_at", UTCDateTime, nullable=True),
    Column("created_at", UTCDateTime, nullable=False),
    Index("ix_requests_buyer_created", "buyer_id", "created_at", "id"),
    Index("ix_requests_status_expires", "status", "expires_at"),
    Index("ix_requests_open_route", "status", "visibility", "origin_country", "destination_country", "created_at", "id"),
)

quotes = Table(
    "quotes",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("request_id", String(40), ForeignKey("shipment_requests.id", ondelete="CASCADE"), nullable=False),
    Column("forwarder_id", String(40), ForeignKey("forwarders.id", ondelete="CASCADE"), nullable=False),
    Column("amount", String(24), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("transit_days", Integer, nullable=False),
    Column("valid_until", UTCDateTime, nullable=False),
    Column("inclusions", JSON, nullable=False),
    Column("exclusions", JSON, nullable=False),
    Column("breakdown", JSON, nullable=False),  # [{label, amount}]
    Column("terms", Text, nullable=True),
    Column("status", String(10), nullable=False),  # submitted | accepted | rejected | withdrawn
    Column("visibility", String(8), nullable=False),  # visible | hidden
    Column("hidden_reason", String(300), nullable=True),
    Column("report_count", Integer, nullable=False, default=0),
    Column("revision", Integer, nullable=False, default=1),
    Column("created_at", UTCDateTime, nullable=False),
    Column("updated_at", UTCDateTime, nullable=False),
    UniqueConstraint("request_id", "forwarder_id", name="uq_quotes_request_forwarder"),
    Index("ix_quotes_request_created", "request_id", "created_at", "id"),
    Index("ix_quotes_forwarder_created", "forwarder_id", "created_at", "id"),
)

ratings = Table(
    "ratings",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("request_id", String(40), ForeignKey("shipment_requests.id", ondelete="CASCADE"), nullable=False),
    Column("forwarder_id", String(40), ForeignKey("forwarders.id", ondelete="CASCADE"), nullable=False),
    Column("buyer_id", String(128), nullable=False),
    Column("stars", Integer, nullable=False),
    Column("comment", String(500), nullable=True),
    Column("created_at", UTCDateTime, nullable=False),
    UniqueConstraint("request_id", name="uq_ratings_request"),
    Index("ix_ratings_forwarder_created", "forwarder_id", "created_at", "id"),
)

reports = Table(
    "reports",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("target_type", String(10), nullable=False),  # request | quote | forwarder
    Column("target_id", String(40), nullable=False),
    Column("reporter_id", String(128), nullable=False),
    Column("reason", String(32), nullable=False),
    Column("details", String(300), nullable=True),  # redacted: no links / emails / phones
    Column("created_at", UTCDateTime, nullable=False),
    UniqueConstraint("target_type", "target_id", "reporter_id", name="uq_reports_once"),
    Index("ix_reports_target", "target_type", "target_id", "created_at"),
    Index("ix_reports_created", "created_at", "id"),
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


def today(clock_now: datetime) -> date:
    return clock_now.astimezone(UTC).date()
