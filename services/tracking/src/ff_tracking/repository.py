"""SQLAlchemy async persistence: one row per shipment, the aggregate stored as JSON."""

from __future__ import annotations

from sqlalchemy import DateTime, String, Text, UniqueConstraint, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

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


def make_engine(url: str) -> AsyncEngine:
    if ":memory:" in url or url.endswith("://"):
        return create_async_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    return create_async_engine(url)


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


__all__ = ["AsyncSession", "Base", "ShipmentRepository", "make_engine"]
