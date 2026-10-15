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
    delete,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ff_demand.dburl import normalize_database_url

metadata = MetaData()
PURGE_BATCH = 1000  # rows examined per retention pass
MAX_LIST = 500  # hard cap for list reads (newest first); unbounded scans are a DoS/latency risk

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
    Column("thread_key", String(64), nullable=True, index=True),  # hash of normalised thread URL
    Column("author_key", String(64), nullable=True, index=True),  # hash of the poster handle
    Column("doc", JSON, nullable=False),
)
# Opt-outs / takedowns: hashes only (never the handle or URL itself). Never purged.
suppressions = Table(
    "suppressions",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("kind", String(16), nullable=False),  # author | thread
    Column("created_at", DateTime(timezone=True), nullable=False),
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

    async def list_signals(self, limit: int = MAX_LIST) -> list[dict]:
        async with self.engine.connect() as c:
            q = select(signals.c.doc).order_by(signals.c.created_at.desc()).limit(limit)
            rows = await c.execute(q)
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
                    thread_key=doc.get("thread_key"),
                    author_key=doc.get("author_key"),
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

    async def list_drafts(self, status: str | None, limit: int = MAX_LIST) -> list[dict]:
        q = select(drafts.c.doc).order_by(drafts.c.created_at.desc()).limit(limit)
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

    async def drafts_by_keys(self, keys: list[str]) -> list[dict]:
        if not keys:
            return []
        q = select(drafts.c.doc).where(
            or_(drafts.c.thread_key.in_(keys), drafts.c.author_key.in_(keys))
        )
        async with self.engine.connect() as c:
            return [r[0] for r in await c.execute(q)]

    async def is_suppressed(self, keys: list[str]) -> bool:
        keys = [k for k in keys if k]
        if not keys:
            return False
        async with self.engine.connect() as c:
            return await self._suppressed(c, keys)

    @staticmethod
    async def _suppressed(c, keys: list[str]) -> bool:
        q = select(func.count()).select_from(suppressions).where(suppressions.c.key.in_(keys))
        return (await c.execute(q)).scalar_one() > 0

    async def add_suppression(self, key: str, kind: str, created_at: datetime, doc: dict) -> bool:
        """Idempotent; returns True when newly recorded. There is deliberately no delete."""
        async with self.engine.begin() as c:
            if await self._suppressed(c, [key]):
                return False
            await c.execute(
                insert(suppressions).values(key=key, kind=kind, created_at=created_at, doc=doc)
            )
        return True

    async def list_suppressions(self, limit: int = MAX_LIST) -> list[dict]:
        async with self.engine.connect() as c:
            q = select(suppressions.c.doc).order_by(suppressions.c.created_at.desc()).limit(limit)
            return [r[0] for r in await c.execute(q)]

    async def approve_draft(
        self,
        doc: dict,
        now: datetime,
        *,
        cap: int,
        day_start: datetime,
        day_end: datetime,
        cooldown_since: datetime,
    ) -> str:
        """Atomic approval: status CAS + opt-out + per-thread/author cooldown + daily cap, all in
        one serialised transaction (process lock + PostgreSQL advisory lock across replicas).
        Returns ok | conflict | opted_out | cooldown | cap."""
        async with self._cap_lock, self.engine.begin() as c:
            if c.dialect.name == "postgresql":
                await c.execute(text("SELECT pg_advisory_xact_lock(727001)"))
            keys = [k for k in (doc.get("thread_key"), doc.get("author_key")) if k]
            if await self._suppressed(c, keys):
                return "opted_out"
            tk, ak = doc.get("thread_key"), doc.get("author_key")
            same = [
                col == v for col, v in ((drafts.c.thread_key, tk), (drafts.c.author_key, ak)) if v
            ]
            if same:
                n = (
                    await c.execute(
                        select(func.count())
                        .select_from(drafts)
                        .where(
                            drafts.c.id != doc["id"],
                            drafts.c.status.in_(("approved", "published")),
                            drafts.c.approved_at >= cooldown_since,
                            or_(*same),
                        )
                    )
                ).scalar_one()
                if n:
                    return "cooldown"
            n = (
                await c.execute(
                    select(func.count())
                    .select_from(drafts)
                    .where(drafts.c.approved_at >= day_start, drafts.c.approved_at < day_end)
                )
            ).scalar_one()
            if n >= cap:
                return "cap"
            res = await c.execute(
                update(drafts)
                .where(drafts.c.id == doc["id"], drafts.c.status == "draft")
                .values(status="approved", doc=doc, approved_at=now, version=drafts.c.version + 1)
            )
            if res.rowcount != 1:
                await c.rollback()
                return "conflict"
        return "ok"

    async def reset_approval(self, doc: dict, expected_status: str) -> bool:
        """approved|draft -> draft with approved_at cleared (an edit voids the approval)."""
        async with self._cap_lock, self.engine.begin() as c:
            res = await c.execute(
                update(drafts)
                .where(drafts.c.id == doc["id"], drafts.c.status == expected_status)
                .values(status="draft", approved_at=None, doc=doc, version=drafts.c.version + 1)
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

    async def purge(
        self, signal_before: datetime | None, rejected_before: datetime | None
    ) -> dict[str, int]:
        """Retention: ignored/no_match signals and rejected drafts (with their signal) only.

        Never touches draft/approved/published drafts or the signals they hang off."""
        out = {"signals": 0, "drafts": 0}
        async with self.engine.begin() as c:
            if rejected_before is not None:
                old = select(drafts.c.id, drafts.c.signal_id).where(
                    drafts.c.status == "rejected", drafts.c.created_at < rejected_before
                )
                rows = (await c.execute(old)).all()
                if rows:
                    ids = [r[0] for r in rows]
                    sids = [r[1] for r in rows]
                    res = await c.execute(delete(drafts).where(drafts.c.id.in_(ids)))
                    out["drafts"] = res.rowcount or 0
                    # drop the signal only when no other draft still references it
                    keep = select(drafts.c.signal_id).where(drafts.c.signal_id.in_(sids))
                    out["signals"] += (
                        await c.execute(
                            delete(signals).where(signals.c.id.in_(sids), signals.c.id.not_in(keep))
                        )
                    ).rowcount or 0
            if signal_before is not None:
                # status lives in the JSON doc (no column): filter in Python, bounded per pass
                cand = (
                    await c.execute(
                        select(signals.c.id, signals.c.doc)
                        .where(
                            signals.c.created_at < signal_before,
                            signals.c.id.not_in(select(drafts.c.signal_id)),
                        )
                        .order_by(signals.c.created_at)
                        .limit(PURGE_BATCH)
                    )
                ).all()
                ids = [r[0] for r in cand if (r[1] or {}).get("status") in ("ignored", "no_match")]
                if ids:
                    out["signals"] += (
                        await c.execute(delete(signals).where(signals.c.id.in_(ids)))
                    ).rowcount or 0
        return out
