"""Deal lifecycle: payments callback + supplier/buyer transitions + immutable event log.

Payment rule: the deal becomes ``paid`` only when every invoice kind payments has told us about is
paid. A kind is *known* once it was settled (paid/refunded) or was reported open via ``other_open_kinds``
of another event. So: both invoices exist -> both must be paid; only one exists -> that one is enough.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ff_rfq.db import DealEventRow, DealRow, OfferRow, RequestRow, ReviewEventRow, ReviewRow
from ff_rfq.domain.enums import DealStatus as D
from ff_rfq.domain.errors import Forbidden, InvalidTransition, NotFound, ValidationFailed
from ff_rfq.domain.state import deal_transition
from ff_rfq.schemas import PaymentStatusCallback
from ff_rfq.service import _iso, deal_dict

SYSTEM = "system:payments"
KINDS = ("commission", "deal_payment")


def _id() -> str:
    return f"dle_{uuid.uuid4().hex}"


def settled(state: dict[str, dict], require_both: bool = False) -> bool:
    """True when at least one invoice is known and all known ones are paid (both kinds if ``require_both``)."""
    if require_both and any(state.get(k, {}).get("status") != "paid" for k in KINDS):
        return False
    return bool(state) and all(v.get("status") == "paid" for v in state.values())


async def _lock_deal(s: AsyncSession, deal_id: str) -> DealRow | None:
    """SELECT ... FOR UPDATE; SQLite ignores it, so take its write lock with a no-op UPDATE first (otherwise two
    connections both read the old status and both apply the transition)."""
    if s.bind is not None and s.bind.dialect.name == "sqlite":
        await s.execute(update(DealRow).where(DealRow.id == deal_id).values(id=DealRow.id))
    return (await s.execute(select(DealRow).where(DealRow.id == deal_id).with_for_update())).scalar_one_or_none()


def event_dict(e: DealEventRow, deal: DealRow) -> dict[str, Any]:
    role = "system" if e.actor == SYSTEM else "buyer" if e.actor == deal.buyer_id else "supplier"
    return {"seq": e.seq, "action": e.action, "actor_role": role, "from_status": e.from_status,
            "to_status": e.to_status, "data": e.data or {}, "created_at": _iso(e.created_at)}


class DealService:
    def __init__(self, engine: AsyncEngine, clock: Callable[[], datetime], require_both: bool = False) -> None:
        self.clock, self.require_both = clock, require_both
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    @staticmethod
    async def _log(s: AsyncSession, deal: DealRow, action: str, actor: str, now: datetime, *,
                   frm: str | None = None, to: str | None = None, event_id: str | None = None,
                   data: dict | None = None) -> None:
        seq = (await s.execute(select(func.count()).select_from(DealEventRow).where(
            DealEventRow.deal_id == deal.id))).scalar_one() + 1
        s.add(DealEventRow(id=_id(), deal_id=deal.id, seq=seq, action=action, actor=actor, from_status=frm,
                           to_status=to, event_id=event_id, data=data, created_at=now))
        await s.flush()

    # ---- internal: payments callback ---------------------------------------------------------
    async def apply_payment_status(self, deal_id: str, body: PaymentStatusCallback) -> dict[str, Any]:
        now = self.clock()
        try:
            async with self._sessions() as s, s.begin():
                deal = await _lock_deal(s, deal_id)
                if deal is None:
                    raise NotFound("Deal not found")
                if await s.scalar(select(DealEventRow.id).where(DealEventRow.event_id == body.event_id)):
                    return self._result("duplicate", deal)
                expected = deal.commission_amount if body.kind == "commission" else deal.subtotal
                if body.amount.currency != deal.currency or body.amount.amount != Decimal(expected):
                    raise ValidationFailed("Amount does not match the deal", code="amount_mismatch",
                                           details={"kind": body.kind, "expected": {"amount": expected, "currency": deal.currency}})
                outcome = await self._apply(s, deal, body, now)
                return self._result(outcome, deal)
        except IntegrityError:  # concurrent delivery of the same event_id
            async with self._sessions() as s, s.begin():
                deal = await s.get(DealRow, deal_id)
                if deal is None or not await s.scalar(select(DealEventRow.id).where(DealEventRow.event_id == body.event_id)):
                    raise
                return self._result("duplicate", deal)

    @staticmethod
    def _result(outcome: str, deal: DealRow) -> dict[str, Any]:
        return {"deal_id": deal.id, "outcome": outcome, "deal_status": deal.status,
                "payment": deal_dict(deal)["payment"]}

    async def _apply(self, s: AsyncSession, deal: DealRow, b: PaymentStatusCallback, now: datetime) -> str:
        state = {k: dict(v) for k, v in (deal.payment_state or {}).items()}
        prev = state.get(b.kind) or {}
        if b.status == "paid" and prev.get("status") == "refunded" and prev.get("invoice_id") == b.invoice_id:
            # refunded is terminal per invoice: a late/replayed 'paid' (outbox reorder) must not re-settle the deal
            frm = D(deal.status)
            await self._log(s, deal, "payment_paid", SYSTEM, now, frm=frm.value, to=frm.value, event_id=b.event_id,
                            data={"kind": b.kind, "invoice_id": b.invoice_id, "outcome": "ignored",
                                  "amount": {"amount": format(b.amount.amount, "f"), "currency": b.amount.currency}})
            return "ignored"
        state[b.kind] = {"invoice_id": b.invoice_id, "status": b.status}
        if b.status == "paid":
            for k in b.other_open_kinds:
                if k != b.kind:
                    state.setdefault(k, {"invoice_id": None, "status": "open"})
        frm = D(deal.status)
        new, outcome = frm, "ignored"
        if b.status == "paid":
            if frm == D.PENDING_PAYMENT and settled(state, self.require_both):
                new, outcome = deal_transition(frm, "mark_paid", deal.id), "applied"
        elif b.kind == "deal_payment":
            if frm in (D.PENDING_PAYMENT, D.PAID):
                new, outcome = deal_transition(frm, "refund", deal.id), "applied"
            elif frm == D.IN_FULFILMENT:
                new, outcome = deal_transition(frm, "dispute", deal.id), "applied"
        elif frm == D.PAID:  # commission refunded before fulfilment: it must be paid again
            new, outcome = deal_transition(frm, "reopen_payment", deal.id), "applied"
        if state != (deal.payment_state or {}):
            deal.payment_state = state
            if outcome == "ignored":
                outcome = "recorded"
        deal.status, deal.updated_at = new.value, now
        if b.status == "refunded" and b.kind == "deal_payment":
            await self._hide_reviews(s, deal.id, now)
        await self._log(s, deal, f"payment_{b.status}", SYSTEM, now, frm=frm.value, to=new.value,
                        event_id=b.event_id, data={"kind": b.kind, "invoice_id": b.invoice_id, "outcome": outcome,
                                                   "amount": {"amount": format(b.amount.amount, "f"),
                                                              "currency": b.amount.currency}})
        return outcome

    @staticmethod
    async def _hide_reviews(s: AsyncSession, deal_id: str, now: datetime) -> None:
        """A refunded / disputed deal is no longer a verified purchase: its review leaves public lists and the
        summary (status ``hidden``, flagged for a moderator). Rows stay for the audit trail."""
        ids = (await s.execute(select(ReviewRow.id).where(ReviewRow.deal_id == deal_id,
                                                          ReviewRow.status == "published"))).scalars().all()
        for rid in ids:
            await s.execute(update(ReviewRow).where(ReviewRow.id == rid).values(
                status="hidden", flagged_for_review=True, updated_at=now))
            s.add(ReviewEventRow(id=f"rve_{uuid.uuid4().hex}", review_id=rid, action="hidden", actor_id=SYSTEM,
                                 snapshot=None, created_at=now))

    # ---- user transitions ----------------------------------------------------------------
    async def _party(self, s: AsyncSession, user: str, deal_id: str) -> DealRow:
        deal = await _lock_deal(s, deal_id)
        if deal is None or user not in (deal.buyer_id, deal.supplier_user_id):
            raise NotFound("Deal not found")  # same answer for unknown and foreign deals (no IDOR probing)
        return deal

    async def _as_supplier(self, s: AsyncSession, user: str, supplier_id: str | None, deal_id: str) -> DealRow:
        deal = await self._party(s, user, deal_id)
        if deal.supplier_user_id != user:
            raise Forbidden("Only the supplier of this deal can do this")
        offer = await s.get(OfferRow, deal.offer_id)
        if offer is not None and offer.supplier_ref and supplier_id != offer.supplier_ref:
            raise Forbidden("Verified supplier identity required", code="supplier_verification_required")
        return deal

    async def start_fulfilment(self, user: str, supplier_id: str | None, deal_id: str) -> dict[str, Any]:
        now = self.clock()
        async with self._sessions() as s, s.begin():
            deal = await self._as_supplier(s, user, supplier_id, deal_id)
            if deal.status == D.IN_FULFILMENT.value:
                return deal_dict(deal)  # idempotent
            frm, new = D(deal.status), deal_transition(D(deal.status), "start_fulfilment", deal.id)
            deal.status, deal.updated_at = new.value, now
            await self._log(s, deal, "fulfilment_started", user, now, frm=frm.value, to=new.value)
            return deal_dict(deal)

    async def delivered(self, user: str, supplier_id: str | None, deal_id: str) -> dict[str, Any]:
        now = self.clock()
        async with self._sessions() as s, s.begin():
            deal = await self._as_supplier(s, user, supplier_id, deal_id)
            if deal.delivered_at is not None:
                return deal_dict(deal)  # idempotent (also after completion)
            if deal.status != D.IN_FULFILMENT.value:
                raise InvalidTransition("deal", deal.status, "delivered", allowed=["start_fulfilment"], entity_id=deal.id)
            deal.delivered_at = deal.updated_at = now
            await self._log(s, deal, "delivered", user, now, frm=deal.status, to=deal.status)
            return deal_dict(deal)

    async def confirm_receipt(self, user: str, deal_id: str) -> dict[str, Any]:
        now = self.clock()
        async with self._sessions() as s, s.begin():
            deal = await self._party(s, user, deal_id)
            if deal.buyer_id != user:
                raise Forbidden("Only the buyer of this deal can confirm receipt")
            if deal.status == D.COMPLETED.value:
                return deal_dict(deal)  # idempotent
            frm, new = D(deal.status), deal_transition(D(deal.status), "confirm_receipt", deal.id)
            deal.status, deal.completed_at, deal.updated_at = new.value, now, now
            await self._log(s, deal, "receipt_confirmed", user, now, frm=frm.value, to=new.value,
                            data={"supplier_marked_delivered": deal.delivered_at is not None})
            return deal_dict(deal)

    async def events(self, user: str, deal_id: str) -> dict[str, Any]:
        async with self._sessions() as s, s.begin():
            deal = await s.get(DealRow, deal_id)
            if deal is None or user not in (deal.buyer_id, deal.supplier_user_id):
                raise NotFound("Deal not found")
            rows = (await s.execute(select(DealEventRow).where(DealEventRow.deal_id == deal_id)
                                    .order_by(DealEventRow.seq))).scalars().all()
            return {"items": [event_dict(e, deal) for e in rows], "total": len(rows)}


    # ---- lookups ---------------------------------------------------------------------------
    async def list_for_user(self, user: str, role: str, status: str | None, p: int, size: int) -> dict[str, Any]:
        """The caller's own deals, newest first (id as tie-break keeps pages stable). Never other parties' deals."""
        mine = {"buyer": DealRow.buyer_id == user, "supplier": DealRow.supplier_user_id == user,
                "any": or_(DealRow.buyer_id == user, DealRow.supplier_user_id == user)}[role]
        cond = [mine] + ([DealRow.status == status] if status else [])
        async with self._sessions() as s, s.begin():
            total = (await s.execute(select(func.count()).select_from(DealRow).where(*cond))).scalar_one()
            rows = (await s.execute(select(DealRow).where(*cond).order_by(DealRow.created_at.desc(), DealRow.id.desc())
                                    .offset((p - 1) * size).limit(size))).scalars().all()
            return {"items": [deal_dict(d) for d in rows], "total": total, "page": p, "page_size": size}

    async def for_request(self, user: str, request_id: str) -> dict[str, Any]:
        """Accepted deal of a request; buyer (request owner) only, 404 for everyone else / no deal yet."""
        async with self._sessions() as s, s.begin():
            d = (await s.execute(select(DealRow).join(RequestRow, RequestRow.id == DealRow.request_id).where(
                DealRow.request_id == request_id, RequestRow.owner_id == user, DealRow.buyer_id == user))).scalar_one_or_none()
            if d is None:
                raise NotFound("Deal not found")
            return deal_dict(d)
