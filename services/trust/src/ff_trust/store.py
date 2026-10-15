"""DB-backed stores: score snapshots (history) and buyer reports (moderation queue).

Both live in the service database (``ff_trust.db``), so they survive restarts. Both are bounded: per-supplier /
total caps and time-based retention (``purge``, run at startup and opportunistically at most once per hour).
Accepted reports are the only rows that influence a score, so retention never deletes them.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, insert, select, update

from ff_trust.db import Database, reports, score_snapshots

REPORT_TYPES = ("fraud", "counterfeit", "non_delivery", "quality", "misrepresentation", "unsafe_product", "other")
REPORT_STATUSES = ("pending_review", "accepted", "rejected")
PURGE_EVERY = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Snapshot:
    at: datetime
    score: int
    band: str
    confidence: int


@dataclass(slots=True)
class Report:
    id: str
    supplier_id: str
    reporter_id: str
    type: str
    text: str
    created_at: datetime
    status: str = "pending_review"
    reviewed_at: datetime | None = None
    low_trust: bool = False


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


class CapacityReached(Exception):
    """The report table is full of accepted reports (which are never evicted)."""


def _default_db() -> Database:
    return Database("sqlite+aiosqlite:///:memory:", True)


class SnapshotStore:
    def __init__(self, db: Database | None = None, max_per_supplier: int = 500, max_total: int = 200_000, retention_days: int = 730, clock: Callable[[], datetime] = _now):
        self.db = db or _default_db()
        self.max_per_supplier, self.max_total, self.retention_days, self.clock = max_per_supplier, max_total, retention_days, clock
        self._last_purge: datetime | None = None

    async def add(self, supplier_id: str, snap: Snapshot) -> None:
        t = score_snapshots
        async with self.db.begin() as conn:
            last = (await conn.execute(select(t.c.score, t.c.band, t.c.confidence).where(t.c.supplier_id == supplier_id).order_by(t.c.at.desc(), t.c.id.desc()).limit(1))).first()
            if last and (last.score, last.band, last.confidence) == (snap.score, snap.band, snap.confidence):
                return  # unchanged: do not store duplicates every cache refresh
            await conn.execute(insert(t).values(supplier_id=supplier_id, at=snap.at, score=snap.score, band=snap.band, confidence=snap.confidence))
            n = (await conn.execute(select(func.count()).select_from(t).where(t.c.supplier_id == supplier_id))).scalar_one()
            if n > self.max_per_supplier:
                old = select(t.c.id).where(t.c.supplier_id == supplier_id).order_by(t.c.at, t.c.id).limit(n - self.max_per_supplier)
                await conn.execute(delete(t).where(t.c.id.in_(old.scalar_subquery())))
        await self._maybe_purge()

    async def add_many(self, snaps: dict[str, Snapshot]) -> None:
        """Batch form of :meth:`add`: one transaction and a constant number of statements for N suppliers
        (latest row per supplier via a window function, one multi-row insert, per-supplier trim only when over cap)."""
        if not snaps:
            return
        t = score_snapshots
        ids = list(snaps)
        async with self.db.begin() as conn:
            ranked = (
                select(t.c.supplier_id, t.c.score, t.c.band, t.c.confidence,
                       func.row_number().over(partition_by=t.c.supplier_id, order_by=(t.c.at.desc(), t.c.id.desc())).label("rn"))
                .where(t.c.supplier_id.in_(ids)).subquery()
            )
            last = {r.supplier_id: (r.score, r.band, r.confidence) for r in (await conn.execute(select(ranked).where(ranked.c.rn == 1))).all()}
            fresh = {sid: sn for sid, sn in snaps.items() if last.get(sid) != (sn.score, sn.band, sn.confidence)}
            if fresh:
                await conn.execute(insert(t), [dict(supplier_id=sid, at=sn.at, score=sn.score, band=sn.band, confidence=sn.confidence) for sid, sn in fresh.items()])
                counts = (await conn.execute(select(t.c.supplier_id, func.count()).where(t.c.supplier_id.in_(list(fresh))).group_by(t.c.supplier_id))).all()
                for sid, n in counts:
                    if n > self.max_per_supplier:
                        old = select(t.c.id).where(t.c.supplier_id == sid).order_by(t.c.at, t.c.id).limit(n - self.max_per_supplier)
                        await conn.execute(delete(t).where(t.c.id.in_(old.scalar_subquery())))
        await self._maybe_purge()

    async def list(self, supplier_id: str) -> list[Snapshot]:
        t = score_snapshots
        async with self.db.begin() as conn:
            rows = (await conn.execute(select(t).where(t.c.supplier_id == supplier_id).order_by(t.c.at, t.c.id))).all()
        return [Snapshot(r.at, r.score, r.band, r.confidence) for r in rows]

    async def purge(self) -> int:
        """Retention + global cap. Returns the number of deleted rows."""
        t, gone = score_snapshots, 0
        self._last_purge = self.clock()
        async with self.db.begin() as conn:
            gone += (await conn.execute(delete(t).where(t.c.at < self._last_purge - timedelta(days=self.retention_days)))).rowcount
            total = (await conn.execute(select(func.count()).select_from(t))).scalar_one()
            if total > self.max_total:
                old = select(t.c.id).order_by(t.c.at, t.c.id).limit(total - self.max_total)
                gone += (await conn.execute(delete(t).where(t.c.id.in_(old.scalar_subquery())))).rowcount
        return gone

    async def _maybe_purge(self) -> None:
        if self._last_purge is None or self.clock() - self._last_purge >= PURGE_EVERY:
            await self.purge()


class ReportStore:
    def __init__(
        self, limit: int = 5, window_seconds: int = 3600, clock: Callable[[], datetime] = _now, max_reports: int = 20000,
        *, db: Database | None = None, retention_days: int = 365, max_low_trust: int = 2000,
    ):  # fmt: skip
        self.db = db or _default_db()
        self.limit, self.window, self.clock, self.max_reports = limit, window_seconds, clock, max_reports
        self.retention_days, self.max_low_trust = retention_days, max_low_trust
        self._last_purge: datetime | None = None

    async def add(self, supplier_id: str, user_id: str, rtype: str, text: str, low_trust: bool = False) -> Report:
        """Store a report as pending_review. Raises RateLimited when the user exceeded the window quota."""
        t = reports
        async with self.db.begin() as conn:
            await self.db.lock(conn, f"report:{user_id}")
            now = self.clock()
            n, first = (await conn.execute(select(func.count(), func.min(t.c.created_at)).where(t.c.reporter_id == user_id, t.c.created_at > now - timedelta(seconds=self.window)))).one()
            if n >= self.limit:
                raise RateLimited(max(1, int(self.window - (now - first).total_seconds())))
            total = (await conn.execute(select(func.count()).select_from(t))).scalar_one()
            low_n = (await conn.execute(select(func.count()).select_from(t).where(t.c.low_trust.is_(True)))).scalar_one() if low_trust else 0
            if low_trust and low_n >= self.max_low_trust:
                # the fresh/unverified bucket is full: it only ever recycles its own rows
                if not await self._evict(conn, low_only=True):
                    raise CapacityReached
            elif total >= self.max_reports and not await self._evict(conn, low_only=low_trust):
                # make room: low-trust rows first (rejected, then pending), then established rejected / pending; accepted
                # stay. A low-trust report never evicts an established account's report.
                raise CapacityReached
            r = Report(uuid.uuid4().hex, supplier_id, user_id, rtype, text, now, low_trust=low_trust)
            await conn.execute(insert(t).values(id=r.id, supplier_id=supplier_id, reporter_id=user_id, type=rtype, text=text, status=r.status, created_at=now, low_trust=low_trust))
        await self._maybe_purge()
        return r

    @staticmethod
    async def _evict(conn, *, low_only: bool) -> bool:
        """Delete one victim: oldest rejected then oldest pending, low-trust bucket first. Accepted rows are never touched."""
        t = reports
        tiers = [True] if low_only else [True, False]
        for low in tiers:
            for status in ("rejected", "pending_review"):
                victim = (await conn.execute(select(t.c.id).where(t.c.status == status, t.c.low_trust.is_(low)).order_by(t.c.created_at).limit(1))).scalar()
                if victim:
                    await conn.execute(delete(t).where(t.c.id == victim))
                    return True
        return False

    @staticmethod
    def _report(row) -> Report:
        m = row._mapping
        return Report(m["id"], m["supplier_id"], m["reporter_id"], m["type"], m["text"], m["created_at"], m["status"], m["reviewed_at"], bool(m.get("low_trust", False)))

    async def get(self, report_id: str) -> Report | None:
        async with self.db.begin() as conn:
            row = (await conn.execute(select(reports).where(reports.c.id == report_id))).first()
        return self._report(row) if row else None

    async def review(self, report_id: str, status: str) -> Report | None:
        """Moderator decision (internal use). Only accepted reports ever influence a score.

        Conditional update on the status that was read: two concurrent reviews cannot both think they moved it."""
        if status not in ("accepted", "rejected"):
            raise ValueError("status must be accepted or rejected")
        t = reports
        async with self.db.begin() as conn:
            row = (await conn.execute(select(t).where(t.c.id == report_id))).first()
            if row is None:
                return None
            r = self._report(row)
            if r.status == status:
                return r
            now = self.clock()
            res = await conn.execute(update(t).where(t.c.id == report_id, t.c.status == r.status).values(status=status, reviewed_at=now))
            if res.rowcount != 1:  # lost a race: report what is stored now
                row = (await conn.execute(select(t).where(t.c.id == report_id))).first()
                return self._report(row) if row else None
            r.status, r.reviewed_at = status, now
            return r

    async def accepted_count(self, supplier_id: str) -> int:
        """Accepted reports counted per DISTINCT reporter: one account cannot multiply its own report."""
        t = reports
        async with self.db.begin() as conn:
            return (await conn.execute(select(func.count(func.distinct(t.c.reporter_id))).where(t.c.supplier_id == supplier_id, t.c.status == "accepted"))).scalar_one()

    async def accepted_counts(self, supplier_ids: list[str]) -> dict[str, int]:
        """:meth:`accepted_count` for many suppliers in one grouped query."""
        if not supplier_ids:
            return {}
        t = reports
        async with self.db.begin() as conn:
            rows = (await conn.execute(select(t.c.supplier_id, func.count(func.distinct(t.c.reporter_id))).where(
                t.c.supplier_id.in_(supplier_ids), t.c.status == "accepted").group_by(t.c.supplier_id))).all()
        return {sid: n for sid, n in rows}

    async def purge(self) -> int:
        """Retention: rejected and stale pending reports older than ``retention_days``. Accepted reports are kept."""
        self._last_purge = self.clock()
        t = reports
        async with self.db.begin() as conn:
            res = await conn.execute(delete(t).where(t.c.status != "accepted", t.c.created_at < self._last_purge - timedelta(days=self.retention_days)))
        return res.rowcount

    async def _maybe_purge(self) -> None:
        if self._last_purge is None or self.clock() - self._last_purge >= PURGE_EVERY:
            await self.purge()
