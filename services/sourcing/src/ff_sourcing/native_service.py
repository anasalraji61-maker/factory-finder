"""Owner-side logic for supplier-owned listings: caps, rate limit, publish gating."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from .adapters.native import DuplicateRef, NativeAdapter, NativeStore, OwnedListing
from .api.errors import ApiError
from .clients.trust import TrustClient
from .domain.moderation import HIDDEN_STATUSES, reason_text, redact, screen_listing
from .domain.native import MAX_IMPORT_ITEMS, ImportItem, ListingWrite, clean_text


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
        imports_per_hour: int = 10,
    ):
        self.adapter = adapter
        self.store: NativeStore = adapter.store
        self.trust = trust
        self.max_per_supplier = max_per_supplier
        self.creates_per_hour = creates_per_hour
        self.imports_per_hour = imports_per_hour
        self._imports: dict[str, deque[float]] = defaultdict(deque)
        self.reports_per_hour = reports_per_hour
        self.report_threshold = report_threshold
        self._reporter_key = reporter_key.encode()
        self._reports: dict[str, deque[float]] = defaultdict(deque)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._mono = monotonic
        self._creates: dict[str, deque[float]] = defaultdict(deque)  # per process
        self.analytics = None  # Analytics (set by main); report counts are best effort
        self.on_change: Callable[[list], Awaitable[object]] | None = (
            None  # price observation hook (best effort)
        )

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

    async def import_listings(
        self, supplier_id: str, raw_items: list, dry_run: bool = False
    ) -> dict:
        """Bulk create/update by external_ref. Per-item results; never reveals other suppliers' data."""
        if not 1 <= len(raw_items) <= MAX_IMPORT_ITEMS:
            raise ApiError(
                422, "validation_error", f"Send between 1 and {MAX_IMPORT_ITEMS} items per call"
            )
        q = self._imports[supplier_id]
        now = self._mono()
        while q and now - q[0] >= 3600:
            q.popleft()
        if len(q) >= self.imports_per_hour:
            retry = int(3600 - (now - q[0])) + 1
            raise ApiError(
                429,
                "rate_limited",
                f"At most {self.imports_per_hour} imports per hour",
                {"retry_after_s": retry},
            )
        if not dry_run:
            q.append(now)

        parsed: list[tuple[ImportItem | None, str | None, str | None]] = []  # (item, code, message)
        for raw in raw_items:
            if not isinstance(raw, dict):
                parsed.append((None, "invalid_item", "Item must be an object"))
                continue
            try:
                parsed.append((ImportItem.model_validate(raw), None, None))
            except Exception as exc:
                errs = getattr(exc, "errors", lambda: [])()
                msg = "; ".join(
                    f"{'.'.join(str(x) for x in e.get('loc', ()))}: {e.get('msg', 'invalid')}"
                    for e in errs[:3]
                )
                parsed.append((None, "validation_error", msg or "Invalid item"))

        existing = await self.store.refs_for(
            supplier_id, [i.external_ref for i, _, _ in parsed if i]
        )
        room = max(0, self.max_per_supplier - await self.store.count(supplier_id))
        seen: set[str] = set()
        results: list[dict] = []
        counts = {"created": 0, "updated": 0, "rejected": 0}
        for idx, (item, code, msg) in enumerate(parsed):
            res: dict = {"index": idx}
            if item is not None:
                res["external_ref"] = item.external_ref
            elif isinstance(raw_items[idx], dict) and isinstance(
                raw_items[idx].get("external_ref"), str
            ):
                res["external_ref"] = raw_items[idx]["external_ref"][:64]
            if item is not None and item.external_ref in seen:
                item, code, msg = (
                    None,
                    "duplicate_in_batch",
                    "external_ref appears more than once in this request",
                )
            if item is None:
                res.update(action="rejected", reason=code, message=msg)
                counts["rejected"] += 1
                results.append(res)
                continue
            seen.add(item.external_ref)
            flagged = self._screen(item)
            lid = existing.get(item.external_ref)
            try:
                if lid is not None:
                    res["action"] = "updated"
                    if not dry_run:
                        row = await self.store.update(
                            supplier_id, lid, item, self._clock(), flagged
                        )
                        if row is None:
                            raise ApiError(404, "listing_not_found", "gone")
                        res["status"] = row.status
                        if row.status == "published":
                            await self._changed(await self._view(row))
                    res["id"] = lid
                else:
                    if room <= 0:
                        res.update(
                            action="rejected",
                            reason="listing_cap_reached",
                            message=f"A supplier can hold at most {self.max_per_supplier} listings",
                        )
                        counts["rejected"] += 1
                        results.append(res)
                        continue
                    res["action"] = "created"
                    if not dry_run:
                        row = await self.store.create(
                            supplier_id,
                            item,
                            self._clock(),
                            flagged,
                            external_ref=item.external_ref,
                        )
                        res["id"], res["status"] = row.id, row.status
                    room -= 1
            except (DuplicateRef, ApiError):
                res.pop("id", None)
                res.update(
                    action="rejected", reason="conflict", message="Could not apply this item; retry"
                )
                counts["rejected"] += 1
                results.append(res)
                continue
            if flagged:
                res["moderation"] = flagged
            counts[res["action"]] += 1
            results.append(res)
        return {"dry_run": dry_run, **counts, "results": results}

    async def list(self, supplier_id: str, status: str | None, page: int, page_size: int) -> dict:
        rows, total = await self.store.list_owned(supplier_id, status, page, page_size)
        cache: dict = {}
        items = [await self.adapter.to_owned(r, cache) for r in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    async def get(self, supplier_id: str, listing_id: str) -> OwnedListing:
        return await self._view(await self._owned(supplier_id, listing_id))

    async def update(self, supplier_id: str, listing_id: str, body: ListingWrite) -> OwnedListing:
        row = await self.store.update(
            supplier_id, listing_id, body, self._clock(), self._screen(body)
        )
        if row is None:
            raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
        view = await self._view(row)
        if row.status == "published":
            await self._changed(view)
        return view

    async def _changed(self, view: OwnedListing) -> None:
        if self.on_change is not None:
            with contextlib.suppress(
                Exception
            ):  # never fail an owner write because of price bookkeeping
                await self.on_change([view])

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
        view = await self._view(row)
        await self._changed(view)
        return view

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
        self,
        user_id: str,
        listing_id: str,
        reason: str,
        details: str | None,
        own_supplier: str | None = None,
    ) -> None:
        ref = self.reporter_ref(user_id)
        q = self._reports[ref]
        now = self._mono()
        while q and now - q[0] >= 3600:
            q.popleft()
        if len(q) >= self.reports_per_hour:
            retry = int(3600 - (now - q[0])) + 1
            raise ApiError(
                429,
                "rate_limited",
                f"At most {self.reports_per_hour} reports per hour",
                {"retry_after_s": retry},
            )
        q.append(now)
        if details:
            details = redact(clean_text(details, multiline=True))[:500] or None
        created, owner = await self.store.add_report(
            listing_id, ref, reason, details, self._clock(), self.report_threshold, own_supplier
        )
        if owner is None:
            raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
        if own_supplier is not None and own_supplier == owner:
            raise ApiError(409, "own_listing", "You cannot report your own listing")
        if created and self.analytics is not None:
            await self.analytics.bump(listing_id, "report")

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
                    {"title": row.title, "status": row.status, "supplier_id": row.supplier_id}
                    if row
                    else None
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
