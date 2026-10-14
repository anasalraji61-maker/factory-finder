"""Owner-side logic for supplier-owned listings: caps, rate limit, publish gating."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime

from .adapters.native import NativeAdapter, NativeStore, OwnedListing
from .api.errors import ApiError
from .clients.trust import TrustClient
from .domain.moderation import HIDDEN_STATUSES, reason_text, redact, screen_listing
from .domain.native import ListingWrite, clean_text


class NativeService:
    def __init__(
        self,
        adapter: NativeAdapter,
        trust: TrustClient,
        max_per_supplier: int = 200,
        creates_per_hour: int = 30,
        reports_per_hour: int = 10,
        report_threshold: int = 3,
        reporter_key: str = "ff-sourcing-reporter",
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.adapter = adapter
        self.store: NativeStore = adapter.store
        self.trust = trust
        self.max_per_supplier = max_per_supplier
        self.creates_per_hour = creates_per_hour
        self.reports_per_hour = reports_per_hour
        self.report_threshold = report_threshold
        self._reporter_key = reporter_key.encode()
        self._reports: dict[str, deque[float]] = defaultdict(deque)
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

    @staticmethod
    def _screen(body: ListingWrite) -> str | None:
        flags = screen_listing(body)
        return reason_text(flags) if flags else None

    # ---- operations -------------------------------------------------------
    async def create(self, supplier_id: str, body: ListingWrite) -> OwnedListing:
        if await self.store.count(supplier_id) >= self.max_per_supplier:
            raise ApiError(
                409,
                "listing_cap_reached",
                f"A supplier can hold at most {self.max_per_supplier} listings",
            )
        q = self._check_rate(supplier_id)
        row = await self.store.create(supplier_id, body, self._clock(), self._screen(body))
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
        row = await self.store.update(supplier_id, listing_id, body, self._clock(), self._screen(body))
        if row is None:
            raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
        return await self._view(row)

    async def delete(self, supplier_id: str, listing_id: str) -> None:
        if not await self.store.delete(supplier_id, listing_id):
            raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")

    async def publish(self, supplier_id: str, listing_id: str) -> OwnedListing:
        row = await self._owned(supplier_id, listing_id)
        if row.status in HIDDEN_STATUSES:
            raise ApiError(
                409,
                "under_moderation",
                "This listing is under moderation and cannot be published",
                {"status": row.status, "reason": row.moderation_reason},
            )
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


    # ---- moderation: user reports ------------------------------------------
    def reporter_ref(self, user_id: str) -> str:
        return hmac.new(self._reporter_key, user_id.encode(), hashlib.sha256).hexdigest()[:32]

    async def report(
        self, user_id: str, listing_id: str, reason: str, details: str | None, own_supplier: str | None = None
    ) -> None:
        ref = self.reporter_ref(user_id)
        q = self._reports[ref]
        now = self._mono()
        while q and now - q[0] >= 3600:
            q.popleft()
        if len(q) >= self.reports_per_hour:
            retry = int(3600 - (now - q[0])) + 1
            raise ApiError(
                429, "rate_limited", f"At most {self.reports_per_hour} reports per hour", {"retry_after_s": retry}
            )
        q.append(now)
        if details:
            details = redact(clean_text(details, multiline=True))[:500] or None
        _, owner = await self.store.add_report(
            listing_id, ref, reason, details, self._clock(), self.report_threshold, own_supplier
        )
        if owner is None:
            raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
        if own_supplier is not None and own_supplier == owner:
            raise ApiError(409, "own_listing", "You cannot report your own listing")

    # ---- moderation: admin ---------------------------------------------------
    async def admin_reports(self, status, listing_id, page, page_size) -> dict:
        pairs, total = await self.store.list_reports(status, listing_id, page, page_size)
        items = [
            {
                "id": r.id,
                "listing_id": r.listing_id,
                "reason": r.reason,
                "details": r.details,
                "status": r.status,
                "reporter_ref": r.reporter_ref[:12],
                "created_at": r.created_at.isoformat(),
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                "listing": (
                    {"title": row.title, "status": row.status, "supplier_id": row.supplier_id} if row else None
                ),
            }
            for r, row in pairs
        ]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def admin_listings(self, status, page, page_size) -> dict:
        pairs, total = await self.store.list_moderated(status, page, page_size)
        items = [
            {
                "id": row.id,
                "title": row.title,
                "supplier_id": row.supplier_id,
                "status": row.status,
                "moderation_source": row.moderation_source,
                "moderation_reason": row.moderation_reason,
                "moderated_at": row.moderated_at.isoformat() if row.moderated_at else None,
                "open_reports": n,
            }
            for row, n in pairs
        ]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def admin_moderate(self, listing_id: str, action: str, reason: str | None = None) -> dict:
        res = await self.store.moderate(listing_id, action, reason, self._clock())
        if res == "not_found":
            raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
        if res == "not_moderated":
            raise ApiError(409, "not_moderated", "Listing is not hidden or pending review")
        return {
            "id": res.id,
            "status": res.status,
            "moderation_source": res.moderation_source,
            "moderation_reason": res.moderation_reason,
        }
