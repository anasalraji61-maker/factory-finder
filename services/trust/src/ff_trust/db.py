"""Tables (SQLAlchemy Core), the async engine wrapper and schema bootstrap.

One database per service (``FF_TRUST_DATABASE_URL``): SQLite by default, PostgreSQL ready. Production schemas come
from Alembic (``alembic upgrade head``); ``create_all`` is only the SQLite/dev convenience.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    TypeDecorator,
    event,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from ff_trust.dburl import normalize_database_url

log = logging.getLogger("ff_trust.db")
metadata = MetaData()

DOC_TYPES_SQL = "'business_license','company_registry_reference','bank_reference','export_license','factory_photos','iso_certificate','other_certificate'"
ACTIONS_SQL = "'submit','approve','reject','revoke','withdraw','set_expiry'"


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


verification_documents = Table(
    "verification_documents", metadata,
    Column("id", String(40), primary_key=True),
    Column("supplier_id", String(128), nullable=False),
    Column("doc_type", String(32), nullable=False),
    Column("issuing_country", String(2), nullable=False),
    Column("files", JSON, nullable=False),  # media-service paths
    Column("number_masked", String(16), nullable=True),  # '****' + last 4 at most; the raw number is never stored
    Column("number_fingerprint", String(64), nullable=True),  # HMAC-SHA256 hex, internal only
    Column("expires_on", Date, nullable=True),
    Column("consent", Boolean, nullable=False),
    Column("status", String(12), nullable=False, server_default="pending"),
    Column("reason", Text, nullable=True),
    Column("reviewed_by", String(80), nullable=True),
    Column("reviewed_at", UTCDateTime, nullable=True),
    Column("approved_on", Date, nullable=True),
    Column("created_at", UTCDateTime, nullable=False),
    CheckConstraint(f"doc_type IN ({DOC_TYPES_SQL})", name="ck_verification_documents_doc_type"),
    CheckConstraint("length(issuing_country) = 2", name="ck_verification_documents_country"),
    CheckConstraint("consent", name="ck_verification_documents_consent"),
    CheckConstraint("status IN ('pending','approved','rejected','withdrawn')", name="ck_verification_documents_status"),
    Index("ix_verification_documents_supplier", "supplier_id", "status"),
    Index("ix_verification_documents_status", "status", "created_at"),
    Index("ix_verification_documents_fingerprint", "number_fingerprint"),
    # one live document per supplier+number (race-safe duplicate guard); closed documents may be resubmitted
    Index(
        "uq_verification_documents_live_fingerprint", "supplier_id", "number_fingerprint", unique=True,
        sqlite_where=text("status IN ('pending','approved') AND number_fingerprint IS NOT NULL"),
        postgresql_where=text("status IN ('pending','approved') AND number_fingerprint IS NOT NULL"),
    ),
)

verification_audit = Table(
    "verification_audit", metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("at", UTCDateTime, nullable=False),
    Column("actor", String(100), nullable=False),
    Column("action", String(16), nullable=False),
    Column("document_id", String(40), nullable=False),
    Column("supplier_id", String(128), nullable=False),
    Column("from_status", String(12), nullable=True),
    Column("to_status", String(12), nullable=True),
    Column("reason", Text, nullable=True),
    Column("detail", Text, nullable=True),
    CheckConstraint(f"action IN ({ACTIONS_SQL})", name="ck_verification_audit_action"),
    Index("ix_verification_audit_document", "document_id", "seq"),
    Index("ix_verification_audit_supplier", "supplier_id", "action", "at"),
)

reports = Table(
    "reports", metadata,
    Column("id", String(40), primary_key=True),
    Column("supplier_id", String(128), nullable=False),
    Column("reporter_id", String(128), nullable=False),
    Column("type", String(24), nullable=False),
    Column("text", Text, nullable=False),
    Column("status", String(16), nullable=False, server_default="pending_review"),
    Column("created_at", UTCDateTime, nullable=False),
    Column("reviewed_at", UTCDateTime, nullable=True),
    CheckConstraint("status IN ('pending_review','accepted','rejected')", name="ck_reports_status"),
    Index("ix_reports_supplier_status", "supplier_id", "status"),
    Index("ix_reports_reporter_created", "reporter_id", "created_at"),
    Index("ix_reports_status_created", "status", "created_at"),
)

score_snapshots = Table(
    "score_snapshots", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("supplier_id", String(128), nullable=False),
    Column("at", UTCDateTime, nullable=False),
    Column("score", Integer, nullable=False),
    Column("band", String(12), nullable=False),
    Column("confidence", Integer, nullable=False),
    Index("ix_score_snapshots_supplier_at", "supplier_id", "at"),
    Index("ix_score_snapshots_at", "at"),
)

trust_meta = Table(
    "trust_meta", metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)

# ---- append-only enforcement for the audit table (database level, not just API level) ----
SQLITE_AUDIT_GUARD = (
    "CREATE TRIGGER trg_verification_audit_no_update BEFORE UPDATE ON verification_audit "
    "BEGIN SELECT RAISE(ABORT, 'verification_audit is append-only'); END",
    "CREATE TRIGGER trg_verification_audit_no_delete BEFORE DELETE ON verification_audit "
    "BEGIN SELECT RAISE(ABORT, 'verification_audit is append-only'); END",
)
PG_AUDIT_FUNCTION = (
    "CREATE OR REPLACE FUNCTION ff_trust_audit_append_only() RETURNS trigger AS $$ "
    "BEGIN RAISE EXCEPTION 'verification_audit is append-only'; END; $$ LANGUAGE plpgsql"
)
PG_AUDIT_TRIGGER = (
    "CREATE TRIGGER trg_verification_audit_append_only BEFORE UPDATE OR DELETE ON verification_audit "
    "FOR EACH ROW EXECUTE FUNCTION ff_trust_audit_append_only()"
)
for _stmt in SQLITE_AUDIT_GUARD:
    event.listen(verification_audit, "after_create", DDL(_stmt).execute_if(dialect="sqlite"))
event.listen(verification_audit, "after_create", DDL(PG_AUDIT_FUNCTION).execute_if(dialect="postgresql"))
event.listen(verification_audit, "after_create", DDL(PG_AUDIT_TRIGGER).execute_if(dialect="postgresql"))


def _sqlite_path(url: str) -> str | None:
    db = make_url(url).database
    return None if db in (None, "", ":memory:") or "mode=memory" in db else db


def make_engine(url: str) -> AsyncEngine:
    url = normalize_database_url(url)
    if not url.startswith("sqlite"):
        return create_async_engine(url, pool_pre_ping=True)
    in_memory = _sqlite_path(url) is None
    engine = create_async_engine(
        url, poolclass=StaticPool if in_memory else NullPool, connect_args={"timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _rec):
        dbapi_conn.isolation_level = None  # we emit BEGIN ourselves (below)
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        if not in_memory:
            # switching to WAL needs a lock the busy handler cannot always wait for (a second process/engine
            # bootstrapping the same fresh file): retry instead of failing the first request with "database is locked"
            for attempt in range(200):
                try:
                    cur.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc) and "busy" not in str(exc) or attempt == 199:
                        raise
                    time.sleep(0.05)
        cur.close()

    @event.listens_for(engine.sync_engine, "begin")
    def _on_begin(conn):  # take the write lock up front: check-then-write transactions cannot interleave
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def now() -> datetime:
    return datetime.now(UTC)


class Database:
    """Engine + lazy schema bootstrap. Every unit of work runs in one transaction via :meth:`begin`."""

    def __init__(self, url: str, auto_create: bool):
        self.url = normalize_database_url(url)
        self.auto_create = auto_create
        self.engine = make_engine(self.url)
        self.is_sqlite = self.url.startswith("sqlite")
        self.is_postgres = self.url.startswith("postgresql")
        self._ready = False

    async def create_all(self) -> None:
        path = _sqlite_path(self.url) if self.is_sqlite else None
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        self._ready = True

    async def ensure(self) -> None:
        if not self._ready:
            if self.auto_create:
                await self.create_all()
            else:
                self._ready = True

    @asynccontextmanager
    async def begin(self):
        await self.ensure()
        async with self.engine.begin() as conn:
            yield conn

    async def lock(self, conn: AsyncConnection, key: str) -> None:
        """Serialise check-then-write sections per key on PostgreSQL (SQLite already holds the write lock)."""
        if self.is_postgres:
            await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key})

    async def ready(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def dispose(self) -> None:
        await self.engine.dispose()
