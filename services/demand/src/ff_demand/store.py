"""SQLite/PostgreSQL storage: JSON documents with the few indexed columns we query on."""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ff_demand.dburl import normalize_database_url

metadata = MetaData()

signals = Table(
    "signals",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("key", String(64), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("doc", JSON, nullable=False),
)
drafts = Table(
    "drafts",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("signal_id", String(40), nullable=False, index=True),
    Column("status", String(16), nullable=False, index=True),
    Column("approved_at", DateTime(timezone=True), nullable=True, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("version", Integer, nullable=False, default=1),
    Column("doc", JSON, nullable=False),
)


class Store:
    def __init__(self, url: str):
        opts = {} if normalize_database_url(url).startswith("sqlite") else {"pool_pre_ping": True}
        self.engine: AsyncEngine = create_async_engine(normalize_database_url(url), **opts)
        self._cap_lock = asyncio.Lock()  # serialises cap-checked approvals within this process

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def signal_by_key(self, key: str) -> dict | None:
        async with self.engine.connect() as c:
            row = (await c.execute(select(signals.c.doc).where(signals.c.key == key))).first()
        return row[0] if row else None

    async def get_signal(self, sid: str) -> dict | None:
        async with self.engine.connect() as c:
            row = (await c.execute(select(signals.c.doc).where(signals.c.id == sid))).first()
        return row[0] if row else None

    async def list_signals(self) -> list[dict]:
        async with self.engine.connect() as c:
            rows = await c.execute(select(signals.c.doc).order_by(signals.c.created_at.desc()))
            return [r[0] for r in rows]

    async def add_signal(self, doc: dict, key: str, created_at: datetime) -> None:
        async with self.engine.begin() as c:
            await c.execute(
                insert(signals).values(id=doc["id"], key=key, created_at=created_at, doc=doc)
            )

    async def update_signal(self, doc: dict) -> None:
        async with self.engine.begin() as c:
            await c.execute(update(signals).where(signals.c.id == doc["id"]).values(doc=doc))

    async def add_draft(self, doc: dict, created_at: datetime) -> None:
        async with self.engine.begin() as c:
            await c.execute(
                insert(drafts).values(
                    id=doc["id"],
                    signal_id=doc["signal_id"],
                    status=doc["status"],
                    created_at=created_at,
                    doc=doc,
                )
            )

    async def get_draft(self, did: str) -> dict | None:
        async with self.engine.connect() as c:
            row = (await c.execute(select(drafts.c.doc).where(drafts.c.id == did))).first()
        return row[0] if row else None

    async def draft_for_signal(self, sid: str) -> dict | None:
        async with self.engine.connect() as c:
            row = (await c.execute(select(drafts.c.doc).where(drafts.c.signal_id == sid))).first()
        return row[0] if row else None

    async def list_drafts(self, status: str | None) -> list[dict]:
        q = select(drafts.c.doc).order_by(drafts.c.created_at.desc())
        if status:
            q = q.where(drafts.c.status == status)
        async with self.engine.connect() as c:
            return [r[0] for r in await c.execute(q)]

    async def save_draft(
        self,
        doc: dict,
        expected_status: str,
        approved_at: datetime | None = None,
        *,
        cap: int | None = None,
        day_start: datetime | None = None,
        day_end: datetime | None = None,
    ) -> bool:
        """Compare-and-set on status. With ``cap``, the approval count for the day is checked in
        the same transaction (returns False when full or the status changed). Cap-checked saves are
        serialised (process lock + a PostgreSQL advisory lock across replicas) so two concurrent
        approvals can never both pass the count check."""
        if cap is None:
            return await self._save_draft(doc, expected_status, approved_at, None, None, None)
        async with self._cap_lock:
            return await self._save_draft(
                doc, expected_status, approved_at, cap, day_start, day_end
            )

    async def _save_draft(
        self,
        doc: dict,
        expected_status: str,
        approved_at: datetime | None,
        cap: int | None,
        day_start: datetime | None,
        day_end: datetime | None,
    ) -> bool:
        async with self.engine.begin() as c:
            if cap is not None:
                if c.dialect.name == "postgresql":
                    await c.execute(text("SELECT pg_advisory_xact_lock(727001)"))
                n = (
                    await c.execute(
                        select(func.count())
                        .select_from(drafts)
                        .where(drafts.c.approved_at >= day_start, drafts.c.approved_at < day_end)
                    )
                ).scalar_one()
                if n >= cap:
                    return False
            vals = {"status": doc["status"], "doc": doc, "version": drafts.c.version + 1}
            if approved_at is not None:
                vals["approved_at"] = approved_at
            res = await c.execute(
                update(drafts)
                .where(drafts.c.id == doc["id"], drafts.c.status == expected_status)
                .values(**vals)
            )
            if res.rowcount != 1:
                await c.rollback()
                return False
        return True

    async def count_approved(self, day_start: datetime, day_end: datetime) -> int:
        async with self.engine.connect() as c:
            return (
                await c.execute(
                    select(func.count())
                    .select_from(drafts)
                    .where(drafts.c.approved_at >= day_start, drafts.c.approved_at < day_end)
                )
            ).scalar_one()
