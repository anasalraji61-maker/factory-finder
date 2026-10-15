"""SQLAlchemy async persistence: one row per shipment, the aggregate stored as JSON."""

from __future__ import annotations

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from ff_tracking.dburl import is_sqlite, normalize_database_url
from ff_tracking.domain.models import Shipment


class Base(DeclarativeBase):
    pass


class ShipmentRow(Base):
    __tablename__ = "shipments"
    __table_args__ = (UniqueConstraint("owner_id", "reference_type", "reference"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    reference_type: Mapped[str] = mapped_column(String(16))
    reference: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    data: Mapped[str] = mapped_column(Text)


class OutboxRow(Base):
    """Notification event records, written once per shipment change (read by the notifications integration)."""

    __tablename__ = "tracking_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    shipment_id: Mapped[str] = mapped_column(String(40), index=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # relay bookkeeping (notifications push): retries with backoff, dead after max attempts / invalid
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)


def make_engine(url: str) -> AsyncEngine:
    url = normalize_database_url(url)
    if ":memory:" in url or url.endswith("://"):
        return create_async_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    if is_sqlite(url):
        return create_async_engine(url)
    return create_async_engine(url, pool_pre_ping=True)


async def export_owner(engine: AsyncEngine, owner_id: str, cap: int = 500) -> dict:
    """Account export: the user's shipments with their stored tracking data (bounded)."""
    async with AsyncSession(engine) as c:
        rows = (await c.scalars(select(ShipmentRow).where(ShipmentRow.owner_id == owner_id).order_by(ShipmentRow.created_at).limit(cap + 1))).all()
    return {"truncated": len(rows) > cap, "data": {"shipments": [
        {"id": r.id, "reference_type": r.reference_type, "reference": r.reference, "status": r.status,
         "created_at": r.created_at.isoformat() if hasattr(r.created_at, "isoformat") else str(r.created_at)}
        for r in rows[:cap]]}}  # fmt: skip


async def erase_owner(engine: AsyncEngine, owner_id: str) -> dict[str, int]:
    """Account erasure: delete the user's shipments and their notification outbox rows."""
    async with engine.begin() as c:
        o = await c.execute(delete(OutboxRow).where(OutboxRow.owner_id == owner_id))
        s = await c.execute(delete(ShipmentRow).where(ShipmentRow.owner_id == owner_id))
    return {"shipments_deleted": int(s.rowcount or 0), "outbox_deleted": int(o.rowcount or 0)}


class ShipmentRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def create_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def find_by_reference(self, owner_id: str, reference_type: str, reference: str) -> Shipment | None:
        async with self._sessions() as s:
            row = (await s.execute(select(ShipmentRow).where(
                ShipmentRow.owner_id == owner_id, ShipmentRow.reference_type == reference_type,
                ShipmentRow.reference == reference))).scalar_one_or_none()
            return Shipment.model_validate_json(row.data) if row else None

    async def get(self, shipment_id: str) -> Shipment | None:
        async with self._sessions() as s:
            row = await s.get(ShipmentRow, shipment_id)
            return Shipment.model_validate_json(row.data) if row else None

    async def save(self, sh: Shipment) -> None:
        async with self._sessions() as s:
            row = await s.get(ShipmentRow, sh.id)
            if row is None:
                row = ShipmentRow(id=sh.id, owner_id=sh.owner_id, reference_type=sh.reference_type.value,
                                  reference=sh.reference, created_at=sh.created_at)
                s.add(row)
            row.status = sh.status.value
            row.data = sh.model_dump_json()
            await s.commit()

    async def count_for_owner(self, owner_id: str) -> int:
        async with self._sessions() as s:
            return (await s.execute(select(func.count()).select_from(ShipmentRow).where(
                ShipmentRow.owner_id == owner_id))).scalar_one()

    async def purge_outbox(self, before) -> int:
        """Retention: drop delivered or dead rows older than ``before`` (pending rows are never purged)."""
        async with self._sessions() as s:
            res = await s.execute(delete(OutboxRow).where(
                OutboxRow.created_at < before,
                (OutboxRow.delivered_at.is_not(None)) | (OutboxRow.dead_at.is_not(None))))
            await s.commit()
            return int(res.rowcount or 0)

    async def delete(self, shipment_id: str) -> None:
        async with self._sessions() as s:
            row = await s.get(ShipmentRow, shipment_id)
            if row:
                await s.delete(row)
                await s.commit()

    async def list(self, owner_id: str, *, status: str | None, page: int, page_size: int) -> tuple[list[Shipment], int]:
        cond = [ShipmentRow.owner_id == owner_id]
        if status:
            cond.append(ShipmentRow.status == status)
        async with self._sessions() as s:
            total = (await s.execute(select(func.count()).select_from(ShipmentRow).where(*cond))).scalar_one()
            rows = (await s.execute(select(ShipmentRow).where(*cond).order_by(
                ShipmentRow.created_at.desc(), ShipmentRow.id).offset((page - 1) * page_size).limit(page_size))).scalars()
            return [Shipment.model_validate_json(r.data) for r in rows], total


    async def add_outbox(self, *, dedupe_key: str, shipment_id: str, owner_id: str, kind: str,
                         payload: str, created_at) -> bool:
        """Insert once per ``dedupe_key``; returns False when the record already exists."""
        async with self._sessions() as s:
            s.add(OutboxRow(dedupe_key=dedupe_key, shipment_id=shipment_id, owner_id=owner_id,
                            kind=kind, payload=payload, created_at=created_at))
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()
                return False
            return True

    async def pending_outbox(self, limit: int = 100) -> list[OutboxRow]:
        async with self._sessions() as s:
            rows = (await s.execute(select(OutboxRow).where(OutboxRow.delivered_at.is_(None))
                                    .order_by(OutboxRow.id).limit(limit))).scalars()
            return list(rows)

    async def due_outbox(self, now, limit: int = 100) -> list[OutboxRow]:
        """Undelivered, not dead, and past their backoff, in id order."""
        async with self._sessions() as s:
            rows = (await s.execute(select(OutboxRow).where(
                OutboxRow.delivered_at.is_(None), OutboxRow.dead_at.is_(None),
                (OutboxRow.next_attempt_at.is_(None)) | (OutboxRow.next_attempt_at <= now),
            ).order_by(OutboxRow.id).limit(limit))).scalars()
            return list(rows)

    async def record_outbox_result(self, outbox_id: int, *, delivered_at=None, error: str | None = None,
                                   next_attempt_at=None, dead_at=None, count_attempt: bool = True) -> None:
        async with self._sessions() as s:
            row = await s.get(OutboxRow, outbox_id)
            if not row:
                return
            if count_attempt:
                row.attempts = (row.attempts or 0) + 1
            row.delivered_at = delivered_at
            row.next_attempt_at = next_attempt_at
            row.dead_at = dead_at
            row.last_error = error[:200] if error else None
            await s.commit()

    async def outbox_stats(self) -> dict:
        async with self._sessions() as s:
            async def count(*cond):
                return (await s.execute(select(func.count()).select_from(OutboxRow).where(*cond))).scalar_one()
            oldest = (await s.execute(select(func.min(OutboxRow.created_at)).where(
                OutboxRow.delivered_at.is_(None), OutboxRow.dead_at.is_(None)))).scalar_one()
            return {
                "pending": await count(OutboxRow.delivered_at.is_(None), OutboxRow.dead_at.is_(None)),
                "retrying": await count(OutboxRow.delivered_at.is_(None), OutboxRow.dead_at.is_(None), OutboxRow.attempts > 0),
                "dead": await count(OutboxRow.dead_at.is_not(None)),
                "delivered": await count(OutboxRow.delivered_at.is_not(None)),
                "oldest_pending_at": oldest.isoformat() if oldest else None,
            }

    async def mark_outbox_delivered(self, outbox_id: int, when) -> None:
        async with self._sessions() as s:
            row = await s.get(OutboxRow, outbox_id)
            if row:
                row.delivered_at = when
                await s.commit()

    async def active(self) -> list[Shipment]:
        """Shipments not yet delivered (the refresh job filters staleness in Python)."""
        async with self._sessions() as s:
            rows = (await s.execute(select(ShipmentRow).where(ShipmentRow.status != "delivered")
                                    .order_by(ShipmentRow.created_at))).scalars()
            return [Shipment.model_validate_json(r.data) for r in rows]


__all__ = ["AsyncSession", "Base", "OutboxRow", "ShipmentRepository", "make_engine"]
