"""Persistence for price observations: dedupe window, per-listing cap, age retention. Never raises into callers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from .db import Base, PriceObservationRow
from .domain.models import Listing
from .domain.pricehistory import Obs, should_record

log = logging.getLogger(__name__)
MAX_BATCH = 100  # observations per call (search page size cap)


class PriceHistoryStore:
    def __init__(
        self,
        engine: AsyncEngine,
        auto_create: bool = True,
        dedupe_hours: float = 6.0,
        max_points: int = 500,
        retention_days: int = 400,
    ):
        self.engine = engine
        self.sm = async_sessionmaker(engine, expire_on_commit=False)
        self._auto_create = auto_create
        self._ready = False
        self.dedupe_hours = dedupe_hours
        self.max_points = max_points
        self.retention_days = retention_days

    async def ensure_ready(self) -> None:
        if self._ready or not self._auto_create:
            return
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._ready = True

    async def record_listings(self, items: list[Listing], now: datetime | None = None) -> int:
        """Record the current headline (min) price of each listing. Mock-catalog listings are synthetic: skipped."""
        batch: dict[str, tuple[Decimal, str, str]] = {}
        for it in items[:MAX_BATCH]:
            if it.source == "mock":
                continue
            batch[it.id] = (it.price.min.amount, it.price.min.currency, it.source)
        if not batch:
            return 0
        try:
            return await self._record(batch, now or datetime.now(UTC))
        except Exception as exc:  # observation is best effort: a failure never breaks search/detail
            log.warning("price observation failed: %s", type(exc).__name__)
            return 0

    async def _record(self, batch: dict[str, tuple[Decimal, str, str]], now: datetime) -> int:
        await self.ensure_ready()
        window_start = now - timedelta(hours=self.dedupe_hours)
        added: list[str] = []
        async with self.sm() as s:
            q = (
                select(PriceObservationRow)
                .where(PriceObservationRow.listing_id.in_(list(batch)), PriceObservationRow.observed_at >= window_start)
                .order_by(PriceObservationRow.observed_at.desc(), PriceObservationRow.id.desc())
            )
            latest: dict[str, Obs] = {}
            for r in (await s.scalars(q)).all():
                latest.setdefault(r.listing_id, Obs(r.observed_at, Decimal(r.price), r.currency))
            for lid, (price, cur, src) in batch.items():
                if should_record(latest.get(lid), price, cur, now, self.dedupe_hours):
                    s.add(PriceObservationRow(listing_id=lid, price=str(price), currency=cur, source=src[:32], observed_at=now))
                    added.append(lid)
            await s.flush()
            for lid in added:
                await self._prune(s, lid, now)
            await s.commit()
        return len(added)

    async def _prune(self, s, lid: str, now: datetime) -> None:
        await s.execute(
            delete(PriceObservationRow).where(
                PriceObservationRow.listing_id == lid,
                PriceObservationRow.observed_at < now - timedelta(days=self.retention_days),
            )
        )
        n = await s.scalar(select(func.count()).select_from(PriceObservationRow).where(PriceObservationRow.listing_id == lid))
        if n and n > self.max_points:
            keep = (
                select(PriceObservationRow.id)
                .where(PriceObservationRow.listing_id == lid)
                .order_by(PriceObservationRow.observed_at.desc(), PriceObservationRow.id.desc())
                .limit(self.max_points)
            )
            ids = set((await s.scalars(keep)).all())
            await s.execute(
                delete(PriceObservationRow).where(PriceObservationRow.listing_id == lid, PriceObservationRow.id.not_in(ids))
            )

    async def series(self, listing_id: str, since: datetime) -> list[Obs]:
        await self.ensure_ready()
        q = (
            select(PriceObservationRow)
            .where(PriceObservationRow.listing_id == listing_id, PriceObservationRow.observed_at >= since)
            .order_by(PriceObservationRow.observed_at, PriceObservationRow.id)
            .limit(self.max_points)
        )
        async with self.sm() as s:
            return [Obs(r.observed_at, Decimal(r.price), r.currency) for r in (await s.scalars(q)).all()]
