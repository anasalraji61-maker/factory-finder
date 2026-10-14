"""'native' source: listings published by verified suppliers, persisted in the service database.

Only ``published`` rows are visible through the normal SourceAdapter interface (search, detail).
Owner CRUD lives in :class:`NativeStore` (used by ``native_service.NativeService``).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ..db import Base, NativeListingRow
from ..domain.models import (
    DayRange,
    GeoPoint,
    ListingDetail,
    Location,
    Money,
    MoneyRange,
    SearchQuery,
    Supplier,
    SupplierSummary,
)
from ..domain.native import ListingWrite
from .base import Health, SourceAdapter

SupplierResolver = Callable[[str], Awaitable[SupplierSummary | None]]


class OwnedListing(ListingDetail):
    """Owner view of a native listing: the public detail plus workflow fields."""

    status: str
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None


def _new_id() -> str:
    return "nat_" + uuid.uuid4().hex[:8]


def _apply(row: NativeListingRow, body: ListingWrite) -> None:
    row.kind, row.condition = body.kind, body.condition
    row.title, row.title_ar = body.title, body.title_ar
    row.description, row.description_ar = body.description, body.description_ar
    row.category = body.category
    row.price_min, row.price_max, row.currency = (
        body.price.min.amount,
        body.price.max.amount,
        body.price.min.currency,
    )
    row.unit, row.moq, row.incoterm = body.unit, body.moq, body.incoterm
    row.unit_weight_kg, row.unit_volume_m3, row.hs_code = (
        body.unit_weight_kg,
        body.unit_volume_m3,
        body.hs_code,
    )
    row.lead_min = body.lead_time_days.min if body.lead_time_days else None
    row.lead_max = body.lead_time_days.max if body.lead_time_days else None
    row.images = list(body.images)
    row.origin = body.origin.model_dump(exclude_none=True)
    row.specs = dict(body.specs)


class NativeStore:
    def __init__(self, engine: AsyncEngine, auto_create: bool = True):
        self.engine = engine
        self.sm = async_sessionmaker(engine, expire_on_commit=False)
        self._auto_create = auto_create
        self._ready = False
        self._lock = asyncio.Lock()

    async def ensure_ready(self) -> None:
        """Create tables lazily on first use (dev/tests). PostgreSQL schemas come from Alembic."""
        if self._ready or not self._auto_create:
            return
        async with self._lock:
            if not self._ready:
                async with self.engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                self._ready = True

    # ---- owner operations ----------------------------------------------
    async def count(self, supplier_id: str) -> int:
        await self.ensure_ready()
        async with self.sm() as s:
            q = select(func.count()).select_from(NativeListingRow)
            return await s.scalar(q.where(NativeListingRow.supplier_id == supplier_id)) or 0

    async def create(self, supplier_id: str, body: ListingWrite, now: datetime) -> NativeListingRow:
        await self.ensure_ready()
        for _ in range(5):
            row = NativeListingRow(
                id=_new_id(), supplier_id=supplier_id, status="draft", created_at=now, updated_at=now
            )
            _apply(row, body)
            try:
                async with self.sm() as s:
                    s.add(row)
                    await s.commit()
                return row
            except IntegrityError:  # id collision: pick another
                continue
        raise RuntimeError("could not allocate a listing id")

    async def get_owned(self, supplier_id: str, listing_id: str) -> NativeListingRow | None:
        await self.ensure_ready()
        async with self.sm() as s:
            row = await s.get(NativeListingRow, listing_id)
        return row if row is not None and row.supplier_id == supplier_id else None

    async def list_owned(
        self, supplier_id: str, status: str | None, page: int, page_size: int
    ) -> tuple[list[NativeListingRow], int]:
        await self.ensure_ready()
        cond = [NativeListingRow.supplier_id == supplier_id]
        if status:
            cond.append(NativeListingRow.status == status)
        async with self.sm() as s:
            total = await s.scalar(select(func.count()).select_from(NativeListingRow).where(*cond))
            rows = (
                await s.scalars(
                    select(NativeListingRow)
                    .where(*cond)
                    .order_by(NativeListingRow.created_at.desc(), NativeListingRow.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        return list(rows), total or 0

    async def update(
        self, supplier_id: str, listing_id: str, body: ListingWrite, now: datetime
    ) -> NativeListingRow | None:
        await self.ensure_ready()
        async with self.sm() as s:
            row = await s.get(NativeListingRow, listing_id)
            if row is None or row.supplier_id != supplier_id:
                return None
            _apply(row, body)
            row.updated_at = now
            await s.commit()
            return row

    async def set_status(
        self, supplier_id: str, listing_id: str, status: str, now: datetime
    ) -> NativeListingRow | None:
        await self.ensure_ready()
        async with self.sm() as s:
            row = await s.get(NativeListingRow, listing_id)
            if row is None or row.supplier_id != supplier_id:
                return None
            row.status, row.updated_at = status, now
            if status == "published":
                row.published_at = now
            await s.commit()
            return row

    async def delete(self, supplier_id: str, listing_id: str) -> bool:
        await self.ensure_ready()
        async with self.sm() as s:
            res = await s.execute(
                delete(NativeListingRow).where(
                    NativeListingRow.id == listing_id, NativeListingRow.supplier_id == supplier_id
                )
            )
            await s.commit()
            return (res.rowcount or 0) > 0

    # ---- public (published only) ----------------------------------------
    async def published(self, limit: int = 200, supplier_id: str | None = None) -> list[NativeListingRow]:
        await self.ensure_ready()
        cond = [NativeListingRow.status == "published"]
        if supplier_id:
            cond.append(NativeListingRow.supplier_id == supplier_id)
        async with self.sm() as s:
            q = select(NativeListingRow).where(*cond)
            q = q.order_by(NativeListingRow.published_at.desc(), NativeListingRow.id).limit(limit)
            return list((await s.scalars(q)).all())

    async def get_published(self, listing_id: str) -> NativeListingRow | None:
        await self.ensure_ready()
        async with self.sm() as s:
            row = await s.get(NativeListingRow, listing_id)
        return row if row is not None and row.status == "published" else None

    async def published_count(self, supplier_id: str) -> int:
        await self.ensure_ready()
        async with self.sm() as s:
            q = select(func.count()).select_from(NativeListingRow)
            q = q.where(
                NativeListingRow.supplier_id == supplier_id, NativeListingRow.status == "published"
            )
            return await s.scalar(q) or 0


def location_of(origin: dict) -> Location:
    point = origin.get("point")
    return Location(
        country_code=origin["country_code"],
        city=origin.get("city"),
        point=GeoPoint(**point) if point else None,
    )


def fallback_supplier(supplier_id: str, origin: dict | None = None) -> SupplierSummary:
    return SupplierSummary(
        id=supplier_id,
        name=supplier_id,
        location=location_of(origin or {"country_code": "ZZ"}),
    )


class NativeAdapter(SourceAdapter):
    id = "native"
    name = "Supplier listings"
    mode = "native"
    compliance = "Listings entered by admin-verified suppliers on this platform; no scraping."
    cacheable = False

    def __init__(self, store: NativeStore, resolver: SupplierResolver | None = None):
        self.store = store
        self.resolver = resolver

    async def summary_for(self, supplier_id: str, origin: dict | None = None) -> SupplierSummary:
        if self.resolver is not None:
            try:
                found = await self.resolver(supplier_id)
            except Exception:
                found = None
            if found is not None:
                return found
        return fallback_supplier(supplier_id, origin)

    async def to_detail(
        self, row: NativeListingRow, cache: dict[str, SupplierSummary] | None = None
    ) -> ListingDetail:
        return await self.to_owned(row, cache, owner_fields=False)  # type: ignore[return-value]

    async def to_owned(
        self,
        row: NativeListingRow,
        cache: dict[str, SupplierSummary] | None = None,
        owner_fields: bool = True,
    ) -> OwnedListing | ListingDetail:
        cache = cache if cache is not None else {}
        sup = cache.get(row.supplier_id)
        if sup is None:
            sup = cache[row.supplier_id] = await self.summary_for(row.supplier_id, row.origin)
        base = dict(
            id=row.id,
            source="native",
            kind=row.kind,
            condition=row.condition,
            title=row.title,
            title_ar=row.title_ar,
            category=row.category,
            images=list(row.images or []),
            price=MoneyRange(
                min=Money(amount=Decimal(row.price_min), currency=row.currency),
                max=Money(amount=Decimal(row.price_max), currency=row.currency),
            ),
            unit=row.unit,
            moq=row.moq,
            incoterm=row.incoterm,
            unit_weight_kg=row.unit_weight_kg,
            unit_volume_m3=row.unit_volume_m3,
            hs_code=row.hs_code,
            lead_time_days=(
                DayRange(min=row.lead_min, max=row.lead_max) if row.lead_min is not None else None
            ),
            supplier=sup,
            origin=location_of(row.origin),
            description=row.description,
            description_ar=row.description_ar,
            specs=dict(row.specs or {}),
        )
        if not owner_fields:
            return ListingDetail(**base)
        return OwnedListing(
            **base,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            published_at=row.published_at,
        )

    # ---- SourceAdapter ----------------------------------------------------
    async def search(self, query: SearchQuery) -> list[ListingDetail]:
        rows = await self.store.published(query.limit)
        cache: dict[str, SupplierSummary] = {}
        return [await self.to_detail(r, cache) for r in rows]

    async def get_listing(self, listing_id: str) -> ListingDetail | None:
        if not listing_id.startswith("nat_"):
            return None
        row = await self.store.get_published(listing_id)
        return await self.to_detail(row) if row is not None else None

    async def get_supplier(self, supplier_id: str) -> Supplier | None:
        rows = await self.store.published(1, supplier_id)
        if not rows:
            return None
        base = await self.summary_for(supplier_id, rows[0].origin)
        count = await self.store.published_count(supplier_id)
        return Supplier(**base.model_dump(), listing_count=count, source="native")

    async def health(self) -> Health:
        try:
            await self.store.ensure_ready()
            async with self.store.engine.connect() as conn:
                from sqlalchemy import text

                await conn.execute(text("SELECT 1"))
            return Health(ok=True)
        except Exception as exc:
            return Health(ok=False, detail=type(exc).__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)
