"""Application service: requests, offers, deals. Every public method runs in one transaction."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ff_rfq.clients.sourcing import SourcingClient
from ff_rfq.config import Settings
from ff_rfq.db import Base, DealRow, OfferRow, RequestRow
from ff_rfq.domain.commission import DEFAULT_USD_RATES, compute_commission
from ff_rfq.domain.enums import DealStatus, ListingKind, OfferStatus, RequestStatus
from ff_rfq.domain.errors import Forbidden, NotFound, ValidationFailed
from ff_rfq.domain.state import offer_transition, request_transition
from ff_rfq.schemas import OfferCreate, RequestCreate

SWEEP_MAX_AGE = timedelta(seconds=30)
LIVE = (RequestStatus.OPEN.value, RequestStatus.NEGOTIATING.value)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _money(amount: str | None, currency: str | None) -> dict[str, str] | None:
    return {"amount": amount, "currency": currency} if amount is not None else None


def _dec(value: Decimal) -> str:
    return format(value.normalize() if value == value.to_integral() else value, "f")


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def request_dict(r: RequestRow, offers_count: int = 0) -> dict[str, Any]:
    return {
        "id": r.id, "owner_id": r.owner_id, "kind": r.kind, "title": r.title, "description": r.description,
        "quantity": r.quantity, "unit": r.unit, "condition": r.condition,
        "target_price": _money(r.target_amount, r.target_currency), "destination": r.destination,
        "deadline": _iso(r.deadline), "attachments": r.attachments or [], "visibility": r.visibility,
        "status": r.status, "offers_count": offers_count, "created_at": _iso(r.created_at),
        "updated_at": _iso(r.updated_at),
    }


def offer_dict(o: OfferRow) -> dict[str, Any]:
    return {
        "id": o.id, "request_id": o.request_id, "supplier_user_id": o.supplier_user_id,
        "supplier_ref": o.supplier_ref, "supplier_name": o.supplier_name,
        "supplier_verified": o.supplier_ref is not None,
        "price": _money(o.price_amount, o.price_currency), "moq": o.moq, "lead_time_days": o.lead_time_days,
        "incoterm": o.incoterm, "valid_until": _iso(o.valid_until), "notes": o.notes, "status": o.status,
        "created_at": _iso(o.created_at), "updated_at": _iso(o.updated_at),
    }


def deal_dict(d: DealRow) -> dict[str, Any]:
    return {
        "id": d.id, "request_id": d.request_id, "offer_id": d.offer_id, "buyer_id": d.buyer_id,
        "supplier_user_id": d.supplier_user_id, "kind": d.kind, "quantity": d.quantity,
        "unit_price": _money(d.unit_price, d.currency), "subtotal": _money(d.subtotal, d.currency),
        "commission": {
            "rate": d.commission_rate, "amount": _money(d.commission_amount, d.currency),
            "min_fee_applied": d.min_fee_applied, "is_estimate": False,
        },
        "supplier_net": _money(format(Decimal(d.subtotal) - Decimal(d.commission_amount), "f"), d.currency),
        "status": d.status,
        "payment": {k: ((d.payment_state or {}).get(k) or {}).get("status") for k in ("commission", "deal_payment")},
        "delivered_at": _iso(d.delivered_at), "completed_at": _iso(d.completed_at),
        "created_at": _iso(d.created_at), "updated_at": _iso(d.updated_at),
    }


def page(items: list, total: int, p: int, size: int) -> dict[str, Any]:
    return {"items": items, "total": total, "page": p, "page_size": size}


class RfqService:
    def __init__(self, engine: AsyncEngine, settings: Settings, sourcing: SourcingClient,
                 clock: Callable[[], datetime]) -> None:
        self.engine, self.settings, self.sourcing, self.clock = engine, settings, sourcing, clock
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        # Sweep throttle: skip the sweep SELECTs while nothing can be due. `_next_due` is the earliest
        # deadline/valid_until seen at the last sweep; `_dirty` is set by writes that add new deadlines.
        self._next_due: datetime | None = None
        self._swept_at: datetime | None = None
        self._dirty = True
        self.rates = {
            ListingKind.PRODUCT: settings.commission_product,
            ListingKind.RAW_MATERIAL: settings.commission_raw_material,
            ListingKind.PRODUCTION_LINE: settings.commission_production_line,
        }

    async def create_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # ---- helpers -------------------------------------------------------------------------
    async def _sweep(self, s: AsyncSession, now: datetime) -> None:
        """Lazily expire requests past their deadline (and their active offers) and stale offers.

        Throttled: reads only touch the DB when something is due (or may be, after a local write or
        SWEEP_MAX_AGE without a sweep, which covers rows written by other processes)."""
        if (not self._dirty and self._swept_at is not None and now - self._swept_at < SWEEP_MAX_AGE
                and (self._next_due is None or now < self._next_due)):
            return
        late = (await s.execute(select(RequestRow).where(
            RequestRow.status.in_(LIVE), RequestRow.deadline.is_not(None), RequestRow.deadline < now))).scalars()
        for r in late:
            r.status = request_transition(RequestStatus(r.status), "expire", r.id).value
            r.updated_at = now
        stale = (await s.execute(select(OfferRow).where(
            OfferRow.status == OfferStatus.ACTIVE.value,
            or_(OfferRow.valid_until.is_not(None) & (OfferRow.valid_until < now),
                OfferRow.request_id.in_(select(RequestRow.id).where(
                    RequestRow.status == RequestStatus.EXPIRED.value)))))).scalars()
        for o in stale:
            o.status = offer_transition(OfferStatus(o.status), "expire", o.id).value
            o.updated_at = now
        await s.flush()
        due = [d for d in (
            (await s.execute(select(func.min(RequestRow.deadline)).where(
                RequestRow.status.in_(LIVE), RequestRow.deadline.is_not(None)))).scalar_one(),
            (await s.execute(select(func.min(OfferRow.valid_until)).where(
                OfferRow.status == OfferStatus.ACTIVE.value, OfferRow.valid_until.is_not(None)))).scalar_one(),
        ) if d is not None]
        self._next_due = min(d if d.tzinfo else d.replace(tzinfo=UTC) for d in due) if due else None
        self._swept_at, self._dirty = now, False

    async def _request(self, s: AsyncSession, request_id: str) -> RequestRow:
        r = await s.get(RequestRow, request_id)
        if r is None:
            raise NotFound("Request not found")
        return r

    async def _offer(self, s: AsyncSession, offer_id: str) -> OfferRow:
        o = await s.get(OfferRow, offer_id)
        if o is None:
            raise NotFound("Offer not found")
        return o

    async def _count(self, s: AsyncSession, request_id: str) -> int:
        return (await s.execute(select(func.count()).select_from(OfferRow).where(
            OfferRow.request_id == request_id))).scalar_one()

    async def _counts(self, s: AsyncSession, ids: list[str]) -> dict[str, int]:
        """Offer counts for many requests in one GROUP BY."""
        if not ids:
            return {}
        res = await s.execute(select(OfferRow.request_id, func.count()).where(
            OfferRow.request_id.in_(ids)).group_by(OfferRow.request_id))
        return {rid: n for rid, n in res.all()}

    async def _active_count(self, s: AsyncSession, request_id: str) -> int:
        return (await s.execute(select(func.count()).select_from(OfferRow).where(
            OfferRow.request_id == request_id, OfferRow.status == OfferStatus.ACTIVE.value))).scalar_one()

    def _check_currency(self, currency: str) -> None:
        if currency not in DEFAULT_USD_RATES:
            from ff_rfq.domain.errors import UnsupportedCurrency
            raise UnsupportedCurrency(f"Currency {currency} is not supported", details={"currency": currency})

    # ---- requests ------------------------------------------------------------------------
    async def create_request(self, user: str, body: RequestCreate) -> dict[str, Any]:
        now = self.clock()
        if body.deadline and body.deadline.astimezone(UTC) <= now:
            raise ValidationFailed("deadline must be in the future", code="invalid_deadline")
        if body.target_price:
            self._check_currency(body.target_price.currency)
        tp = body.target_price
        row = RequestRow(
            id=_id("req"), owner_id=user, kind=body.kind.value, title=body.title, description=body.description,
            quantity=_dec(body.quantity), unit=body.unit, condition=body.condition.value,
            target_amount=format(tp.amount, "f") if tp else None, target_currency=tp.currency if tp else None,
            destination=body.destination.model_dump() if body.destination else None,
            deadline=body.deadline, attachments=body.attachments, visibility=body.visibility.value,
            status=RequestStatus.OPEN.value, created_at=now, updated_at=now,
        )
        async with self._sessions() as s, s.begin():
            s.add(row)
        if row.deadline is not None:
            self._dirty = True
        return request_dict(row)

    async def list_requests(self, user: str, *, scope: str, status: str | None, kind: str | None,
                            p: int, size: int) -> dict[str, Any]:
        cond = [RequestRow.owner_id == user] if scope == "mine" else [
            RequestRow.owner_id != user, RequestRow.visibility == "public", RequestRow.status.in_(LIVE)]
        if status and scope == "mine":
            cond.append(RequestRow.status == status)
        if kind:
            cond.append(RequestRow.kind == kind)
        async with self._sessions() as s, s.begin():
            await self._sweep(s, self.clock())
            total = (await s.execute(select(func.count()).select_from(RequestRow).where(*cond))).scalar_one()
            rows = (await s.execute(select(RequestRow).where(*cond).order_by(
                RequestRow.created_at.desc(), RequestRow.id).offset((p - 1) * size).limit(size))).scalars().all()
            counts = await self._counts(s, [r.id for r in rows])
            items = [request_dict(r, counts.get(r.id, 0)) for r in rows]
        return page(items, total, p, size)

    async def get_request(self, user: str, request_id: str) -> dict[str, Any]:
        async with self._sessions() as s, s.begin():
            await self._sweep(s, self.clock())
            r = await self._request(s, request_id)
            if r.owner_id != user and r.visibility != "public":  # private = owner + suppliers who offered
                mine = (await s.execute(select(func.count()).select_from(OfferRow).where(
                    OfferRow.request_id == r.id, OfferRow.supplier_user_id == user))).scalar_one()
                if not mine:
                    raise NotFound("Request not found")
            return request_dict(r, await self._count(s, r.id))

    async def close_request(self, user: str, request_id: str) -> dict[str, Any]:
        now = self.clock()
        async with self._sessions() as s, s.begin():
            await self._sweep(s, now)
            r = await self._request(s, request_id)
            if r.owner_id != user:
                raise Forbidden("Only the buyer can close this request")
            r.status = request_transition(RequestStatus(r.status), "close", r.id).value
            r.updated_at = now
            offers = (await s.execute(select(OfferRow).where(
                OfferRow.request_id == r.id, OfferRow.status == OfferStatus.ACTIVE.value))).scalars()
            for o in offers:
                o.status = offer_transition(OfferStatus(o.status), "reject", o.id).value
                o.updated_at = now
            return request_dict(r, await self._count(s, r.id))

    async def suggestions(self, user: str, request_id: str, limit: int) -> dict[str, Any]:
        async with self._sessions() as s, s.begin():
            r = await self._request(s, request_id)
            if r.owner_id != user:
                raise Forbidden("Only the buyer can see suggestions")
            kind, title, cond = r.kind, r.title, r.condition
        items = await self.sourcing.search(title, kind, cond, limit)
        return {"request_id": request_id, "items": items[:limit]}

    # ---- offers --------------------------------------------------------------------------
    async def create_offer(self, user: str, request_id: str, body: OfferCreate, supplier_id: str | None = None) -> dict[str, Any]:
        """Offer owner is the caller (X-User-Id). supplier_ref is the gateway-verified X-Supplier-Id or None;
        a client-supplied body.supplier_ref is ignored. supplier_name is only a display label."""
        now = self.clock()
        self._check_currency(body.price.currency)
        if body.valid_until and body.valid_until.astimezone(UTC) <= now:
            raise ValidationFailed("valid_until must be in the future", code="invalid_valid_until")
        async with self._sessions() as s, s.begin():
            await self._sweep(s, now)
            r = await self._request(s, request_id)
            if r.owner_id == user:
                raise Forbidden("You cannot offer on your own request")
            r.status = request_transition(RequestStatus(r.status), "receive_offer", r.id).value
            r.updated_at = now
            o = OfferRow(
                id=_id("off"), request_id=r.id, supplier_user_id=user, supplier_ref=supplier_id,
                supplier_name=body.supplier_name, price_amount=format(body.price.amount, "f"),
                price_currency=body.price.currency, moq=body.moq, lead_time_days=body.lead_time_days,
                incoterm=body.incoterm.value if body.incoterm else None, valid_until=body.valid_until,
                notes=body.notes, status=OfferStatus.ACTIVE.value, created_at=now, updated_at=now)
            s.add(o)
            if o.valid_until is not None:
                self._dirty = True
            return offer_dict(o)

    async def list_offers(self, user: str, request_id: str, status: str | None, p: int, size: int) -> dict[str, Any]:
        async with self._sessions() as s, s.begin():
            await self._sweep(s, self.clock())
            r = await self._request(s, request_id)
            cond = [OfferRow.request_id == r.id]
            if r.owner_id != user:  # suppliers only see their own offers
                cond.append(OfferRow.supplier_user_id == user)
            if status:
                cond.append(OfferRow.status == status)
            total = (await s.execute(select(func.count()).select_from(OfferRow).where(*cond))).scalar_one()
            rows = (await s.execute(select(OfferRow).where(*cond).order_by(
                OfferRow.created_at.desc(), OfferRow.id).offset((p - 1) * size).limit(size))).scalars().all()
            return page([offer_dict(o) for o in rows], total, p, size)

    async def _offer_action(self, user: str, offer_id: str, action: str) -> dict[str, Any]:
        now = self.clock()
        async with self._sessions() as s, s.begin():
            await self._sweep(s, now)
            o = await self._offer(s, offer_id)
            r = await self._request(s, o.request_id)
            if action == "withdraw" and o.supplier_user_id != user:
                raise Forbidden("Only the offering supplier can withdraw this offer")
            if action == "reject" and r.owner_id != user:
                raise Forbidden("Only the buyer can reject offers")
            o.status = offer_transition(OfferStatus(o.status), action, o.id).value
            o.updated_at = now
            await s.flush()
            if await self._active_count(s, r.id) == 0 and r.status == RequestStatus.NEGOTIATING.value:
                r.status = request_transition(RequestStatus(r.status), "release", r.id).value
                r.updated_at = now
            return offer_dict(o)

    async def withdraw_offer(self, user: str, offer_id: str) -> dict[str, Any]:
        return await self._offer_action(user, offer_id, "withdraw")

    async def reject_offer(self, user: str, offer_id: str) -> dict[str, Any]:
        return await self._offer_action(user, offer_id, "reject")

    async def accept_offer(self, user: str, offer_id: str) -> dict[str, Any]:
        now = self.clock()
        async with self._sessions() as s, s.begin():
            await self._sweep(s, now)
            o = await self._offer(s, offer_id)
            r = await self._request(s, o.request_id)
            if r.owner_id != user:
                raise Forbidden("Only the buyer can accept offers")
            # Validate both machines before mutating anything.
            new_request = request_transition(RequestStatus(r.status), "award", r.id)
            new_offer = offer_transition(OfferStatus(o.status), "accept", o.id)
            kind = ListingKind(r.kind)
            qty, unit_price = Decimal(r.quantity), Decimal(o.price_amount)
            subtotal = (qty * unit_price).quantize(Decimal("0.01"))
            fee = compute_commission(subtotal, o.price_currency, kind, rates=self.rates,
                                     min_fee_usd=self.settings.min_commission_usd)
            others = (await s.execute(select(OfferRow).where(
                OfferRow.request_id == r.id, OfferRow.id != o.id,
                OfferRow.status == OfferStatus.ACTIVE.value))).scalars()
            for other in others:
                other.status = offer_transition(OfferStatus(other.status), "reject", other.id).value
                other.updated_at = now
            o.status, o.updated_at = new_offer.value, now
            r.status, r.updated_at = new_request.value, now
            deal = DealRow(
                id=_id("deal"), request_id=r.id, offer_id=o.id, buyer_id=r.owner_id,
                supplier_user_id=o.supplier_user_id, kind=r.kind, quantity=r.quantity,
                unit_price=o.price_amount, currency=o.price_currency, subtotal=format(subtotal, "f"),
                commission_rate=format(fee.rate, "f"), commission_amount=format(fee.amount, "f"),
                min_fee_applied=fee.min_fee_applied, status=DealStatus.PENDING_PAYMENT.value,
                created_at=now, updated_at=now)
            s.add(deal)
            return deal_dict(deal)

    async def get_deal(self, user: str, deal_id: str) -> dict[str, Any]:
        async with self._sessions() as s, s.begin():
            d = await s.get(DealRow, deal_id)
            if d is None or user not in (d.buyer_id, d.supplier_user_id):
                raise NotFound("Deal not found")
            return deal_dict(d)
