"""Owner-side logic for supplier-owned listings: caps, rate limit, publish gating."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime

from .adapters.native import NativeAdapter, NativeStore, OwnedListing
from .api.errors import ApiError
from .clients.trust import TrustClient
from .domain.native import ListingWrite


class NativeService:
    def __init__(
        self,
        adapter: NativeAdapter,
        trust: TrustClient,
        max_per_supplier: int = 200,
        creates_per_hour: int = 30,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.adapter = adapter
        self.store: NativeStore = adapter.store
        self.trust = trust
        self.max_per_supplier = max_per_supplier
        self.creates_per_hour = creates_per_hour
        self._clock = clock or (lambda: datetime.now(UTC))
        self._mono = monotonic
        self._creates: dict[str, deque[float]] = defaultdict(deque)  # per process

    # ---- helpers ----------------------------------------------------------
    async def _view(self, row) -> OwnedListing:
        return await self.adapter.to_owned(row)  # type: ignore[return-value]

    async def _owned(self, supplier_id: str, listing_id: str):
        row = await self.store.get_owned(supplier_id, listing_id)
        if row is None:  # also covers other suppliers' ids: never reveal existence
            raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
        return row

    def _check_rate(self, supplier_id: str) -> deque[float]:
        q = self._creates[supplier_id]
        now = self._mono()
        while q and now - q[0] >= 3600:
            q.popleft()
        if len(q) >= self.creates_per_hour:
            retry = int(3600 - (now - q[0])) + 1
            raise ApiError(
                429,
                "rate_limited",
                f"At most {self.creates_per_hour} listings can be created per hour",
                {"retry_after_s": retry},
            )
        return q

    # ---- operations -------------------------------------------------------
    async def create(self, supplier_id: str, body: ListingWrite) -> OwnedListing:
        if await self.store.count(supplier_id) >= self.max_per_supplier:
            raise ApiError(
                409,
                "listing_cap_reached",
                f"A supplier can hold at most {self.max_per_supplier} listings",
            )
        q = self._check_rate(supplier_id)
        row = await self.store.create(supplier_id, body, self._clock())
        q.append(self._mono())
        return await self._view(row)

    async def list(self, supplier_id: str, status: str | None, page: int, page_size: int) -> dict:
        rows, total = await self.store.list_owned(supplier_id, status, page, page_size)
        cache: dict = {}
        items = [await self.adapter.to_owned(r, cache) for r in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get(self, supplier_id: str, listing_id: str) -> OwnedListing:
        return await self._view(await self._owned(supplier_id, listing_id))

    async def update(self, supplier_id: str, listing_id: str, body: ListingWrite) -> OwnedListing:
        row = await self.store.update(supplier_id, listing_id, body, self._clock())
        if row is None:
            raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
        return await self._view(row)

    async def delete(self, supplier_id: str, listing_id: str) -> None:
        if not await self.store.delete(supplier_id, listing_id):
            raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")

    async def publish(self, supplier_id: str, listing_id: str) -> OwnedListing:
        await self._owned(supplier_id, listing_id)
        try:  # fail closed: a missing/unknown trust verdict never lets a listing go live
            info = await self.trust.get(supplier_id)
        except Exception:
            info = None
        if info is None or info.band == "unknown":
            raise ApiError(
                503, "trust_unavailable", "Supplier trust could not be checked; try again later"
            )
        if info.band == "red":
            raise ApiError(
                403,
                "trust_blocked",
                "Publishing is blocked while the supplier trust band is red",
                {"trust_band": "red"},
            )
        row = await self.store.set_status(supplier_id, listing_id, "published", self._clock())
        return await self._view(row)

    async def unpublish(self, supplier_id: str, listing_id: str) -> OwnedListing:
        row = await self._owned(supplier_id, listing_id)
        if row.status != "published":
            raise ApiError(409, "not_published", "Only a published listing can be unpublished")
        row = await self.store.set_status(supplier_id, listing_id, "archived", self._clock())
        return await self._view(row)
