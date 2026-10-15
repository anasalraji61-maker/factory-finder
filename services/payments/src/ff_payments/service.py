"""PaymentsService: all business logic (routes stay thin). Money = Decimal everywhere, strings at rest."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import secrets
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ff_payments import webhooks
from ff_payments.clients.deals import DealClient, NotifyRejected
from ff_payments.config import Settings
from ff_payments.db import (
    Base,
    InvoiceRow,
    LedgerEntryRow,
    OutboxEventRow,
    PaymentAttemptRow,
    WebhookEventRow,
)
from ff_payments.domain import ledger, state
from ff_payments.domain.commission import DEFAULT_USD_RATES, compute_commission
from ff_payments.domain.enums import Direction, InvoiceKind, InvoiceStatus, ListingKind
from ff_payments.domain.errors import (
    Conflict,
    Forbidden,
    InvalidTransition,
    NotFound,
    TooManyInvoices,
    UpstreamUnavailable,
    ValidationFailed,
)
from ff_payments.providers.base import InvoiceSpec, Observation, PaymentProvider, TrackedInvoice
from ff_payments.schemas import InvoiceCreate, WebhookEvent

S = InvoiceStatus
CENT = Decimal("0.01")
MICRO = Decimal("0.000001")
PLATFORM = "platform"
EVENT_TARGET = {"payment.confirming": S.CONFIRMING, "payment.confirmed": S.PAID,
                "payment.failed": S.FAILED, "payment.expired": S.EXPIRED}
REORG_GRACE = timedelta(minutes=30)
LATE_WINDOW = timedelta(days=7)  # how long after expiry the sweep keeps looking for a late transfer
DEAD_DEAL_STATES = frozenset({"refunded", "disputed"})
REVIEW_LATE = "late_payment_review"  # money arrived for an expired / cancelled invoice: a human decides
REVIEW_AMOUNT = "amount_mismatch_review"  # a provider says "paid" with an amount that is not the invoice's
REVIEW_REASONS = (REVIEW_LATE, REVIEW_AMOUNT)
KNOWN_PROVIDERS = ("mock", "usdt_tron")


def _iso(d: datetime | None) -> str | None:
    return d.isoformat().replace("+00:00", "Z") if d else None


def _money(amount: str, currency: str) -> dict[str, str]:
    return {"amount": amount, "currency": currency}


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def _new_memo() -> str:
    return "FF-" + base64.b32encode(secrets.token_bytes(7)).decode().rstrip("=")[:10]


def normalize_amount(value: Decimal, currency: str) -> str:
    """Fiat: exactly 2 decimals; USDT: up to 6. Extra precision is rejected, never rounded away."""
    q = MICRO if currency == "USDT" else CENT
    if value != value.quantize(q):
        raise ValidationFailed(f"Amount has too many decimals for {currency}", code="invalid_amount")
    return format(value.quantize(q), "f")


def invoice_dict(r: InvoiceRow) -> dict[str, Any]:
    return {
        "id": r.id, "deal_id": r.deal_id, "payer_user_id": r.payer_user_id, "payee": r.payee,
        "kind": r.kind, "amount": _money(r.amount, r.currency), "status": r.status,
        "status_reason": r.status_reason, "expires_at": _iso(r.expires_at), "provider": r.provider,
        "provider_ref": r.provider_ref, "pay_address": r.pay_address, "pay_url": r.pay_url,
        "pay_amount": _money(r.pay_amount, r.pay_currency or r.currency) if r.pay_amount else None,
        "memo": r.memo, "user_memo": r.user_memo, "tx_ref": r.tx_ref, "confirmations": r.confirmations,
        "paid_at": _iso(r.paid_at), "created_at": _iso(r.created_at), "updated_at": _iso(r.updated_at),
    }


def _for_viewer(d: dict[str, Any], r: InvoiceRow, user: str | None, admin: bool) -> dict[str, Any]:
    """The memo is free text typed by the payer: the payee (and anyone else) never sees it."""
    if not admin and r.payer_user_id != user:
        d["user_memo"] = None
    return d


def ledger_dict(e: LedgerEntryRow) -> dict[str, Any]:
    return {"id": e.id, "group_id": e.group_id, "invoice_id": e.invoice_id, "account": e.account,
            "direction": e.direction, "amount": _money(e.amount, e.currency), "reason": e.reason,
            "created_at": _iso(e.created_at)}


class PaymentsService:
    def __init__(self, engine: AsyncEngine, settings: Settings, provider: PaymentProvider | None,
                 deals: DealClient, clock: Callable[[], datetime]) -> None:
        self.engine, self.settings, self.provider, self.deals, self.clock = engine, settings, provider, deals, clock
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def create_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # ---- helpers -------------------------------------------------------------------------
    def _rates(self) -> dict[ListingKind, Decimal]:
        c = self.settings
        return {ListingKind.PRODUCT: c.commission_product, ListingKind.RAW_MATERIAL: c.commission_raw_material,
                ListingKind.PRODUCTION_LINE: c.commission_production_line}

    @staticmethod
    def _visible(r: InvoiceRow, user: str | None, admin: bool) -> bool:
        return admin or (user is not None and user in (r.payer_user_id, r.payee))

    async def _load(self, s: AsyncSession, invoice_id: str, user: str | None, admin: bool) -> InvoiceRow:
        r = await s.get(InvoiceRow, invoice_id)
        if r is None or not self._visible(r, user, admin):
            raise NotFound("Invoice not found", code="invoice_not_found")  # 404 for non-owners too (no probing)
        await self._expire_if_due(s, r)
        return r

    async def _expire_if_due(self, s: AsyncSession, r: InvoiceRow) -> None:
        now = self.clock()
        if r.status in (S.PENDING, S.AWAITING_PAYMENT) and r.expires_at <= now:
            try:
                await self._move(s, r, S.EXPIRED, reason="expired")
                await s.commit()
            except Conflict:  # a payment landed first: show the fresh state
                await s.rollback()
                await s.refresh(r)

    async def _move(self, s: AsyncSession, r: InvoiceRow, target: S, *, reason: str | None = None,
                    tx_ref: str | None = None, confirmations: int | None = None) -> None:
        """Apply a validated transition (and its ledger effect). Caller commits."""
        now = self.clock()
        old = r.status
        state.require(S(old), target, r.id)
        if r in s.new:
            await s.flush()
        # compare-and-set on the stored status: a concurrent writer (sweep vs webhook vs another worker)
        # that already moved this invoice makes us fail instead of double-posting the ledger
        res = await s.execute(update(InvoiceRow).where(InvoiceRow.id == r.id, InvoiceRow.status == old)
                              .values(status=target.value).execution_options(synchronize_session=False))
        if res.rowcount != 1:
            raise Conflict("Invoice changed concurrently; retry", code="concurrent_update")
        r.status, r.updated_at = target.value, now
        if reason:
            r.status_reason = reason
        if tx_ref:
            r.tx_ref = tx_ref
        if confirmations is not None:
            r.confirmations = confirmations
        if target == S.PAID:
            r.paid_at = now
            if r.status_reason in REVIEW_REASONS:
                r.status_reason = None
            await self._post(s, r, ledger.payment_legs(provider=r.provider, payee=r.payee, kind=r.kind,
                                                       amount=Decimal(r.amount), currency=r.currency), "payment")
        elif target == S.REFUNDED:
            rows = (await s.execute(select(LedgerEntryRow).where(
                LedgerEntryRow.invoice_id == r.id, LedgerEntryRow.reason == "payment"))).scalars().all()
            legs = [ledger.Leg(e.account, Direction(e.direction), Decimal(e.amount), e.currency) for e in rows]
            await self._post(s, r, ledger.refund_legs(legs), "refund")
        if target in (S.PAID, S.REFUNDED):
            await self._enqueue(s, r, target, now)
        att = (await s.execute(select(PaymentAttemptRow).where(PaymentAttemptRow.invoice_id == r.id)
                               .order_by(PaymentAttemptRow.created_at.desc()).limit(1))).scalar_one_or_none()
        if att and target in (S.CONFIRMING, S.PAID, S.FAILED):
            att.status = {S.CONFIRMING: "confirming", S.PAID: "confirmed", S.FAILED: "failed"}[target]
            att.tx_ref, att.updated_at = tx_ref or att.tx_ref, now

    async def _enqueue(self, s: AsyncSession, r: InvoiceRow, target: S, now: datetime) -> None:
        """Queue the rfq callback in the SAME transaction as the settlement (never lost, never blocks it)."""
        others = (await s.execute(select(InvoiceRow.kind).where(
            InvoiceRow.deal_id == r.deal_id, InvoiceRow.id != r.id, InvoiceRow.kind != r.kind,
            InvoiceRow.status.in_([x.value for x in state.OPEN])))).scalars().all()
        event_id = f"{r.id}:{target.value}"
        s.add(OutboxEventRow(
            id=f"obx_{time.time_ns():020d}_{uuid.uuid4().hex[:6]}", event_id=event_id, deal_id=r.deal_id,
            payload={"invoice_id": r.id, "kind": r.kind, "status": target.value,
                     "amount": _money(r.amount, r.currency), "event_id": event_id,
                     "other_open_kinds": sorted(set(others))},
            status="pending", attempts=0, next_attempt_at=now, created_at=now, updated_at=now))

    async def _post(self, s: AsyncSession, r: InvoiceRow, legs: list[ledger.Leg], reason: str) -> None:
        ledger.check_balanced(legs)
        now, group = self.clock(), _uid("grp")
        for leg in legs:
            s.add(LedgerEntryRow(id=_uid("led"), group_id=group, invoice_id=r.id, account=leg.account,
                                 direction=leg.direction.value, amount=format(leg.amount, "f"),
                                 currency=leg.currency, reason=reason, created_at=now))

    # ---- invoices ------------------------------------------------------------------------
    async def create_invoice(self, user: str | None, admin: bool, body: InvoiceCreate) -> tuple[dict[str, Any], bool]:
        if self.provider is None:
            raise _Disabled()
        payer, payee, amount, currency = await self._resolve(user, admin, body)
        now = self.clock()
        ttl = body.expires_in_minutes if admin and body.expires_in_minutes else self.settings.invoice_ttl_minutes
        for _ in range(4):
            async with self.sessions() as s:
                existing = await self._live_invoice(s, body, payer)
                if existing is not None:
                    await self._expire_if_due(s, existing)
                    if existing.status != S.EXPIRED.value:
                        return invoice_dict(existing), False
                if not admin:
                    await self._check_quota(s, payer, now)
                invoice_id = _uid("inv")
                memo = _new_memo()
                taken = frozenset((await s.execute(select(InvoiceRow.pay_amount).where(
                    InvoiceRow.provider == self.provider.name, InvoiceRow.pay_amount.is_not(None),
                    InvoiceRow.status.in_([S.AWAITING_PAYMENT.value, S.CONFIRMING.value])))).scalars().all())
                charge = await self.provider.create(InvoiceSpec(invoice_id, memo, Decimal(amount), currency, taken))
                row = InvoiceRow(
                    id=invoice_id, deal_id=body.deal_id, payer_user_id=payer, payee=payee, kind=body.kind.value,
                    amount=amount, currency=currency, status=S.PENDING.value,
                    expires_at=now + timedelta(minutes=ttl), provider=self.provider.name, memo=memo,
                    user_memo=body.memo, confirmations=0, created_at=now, updated_at=now)
                try:
                    s.add(row)
                    await self._move(s, row, S.AWAITING_PAYMENT)
                    row.provider_ref, row.pay_address, row.pay_url = charge.provider_ref, charge.pay_address, charge.pay_url
                    if charge.pay_amount is not None:
                        row.pay_currency = charge.pay_currency or currency
                        row.pay_amount = format(charge.pay_amount, "f")
                    s.add(PaymentAttemptRow(id=_uid("att"), invoice_id=invoice_id, provider=self.provider.name,
                                            provider_ref=charge.provider_ref, status="created", amount=amount,
                                            currency=currency, created_at=now, updated_at=now))
                    await s.commit()
                except IntegrityError:
                    # lost a race: a concurrent identical request created the live invoice (return it, never a
                    # second charge) or took our payment-amount suffix (retry with a fresh one)
                    await s.rollback()
                    continue
                return invoice_dict(row), True
        raise Conflict("Could not create the invoice; retry", code="concurrent_update")

    @staticmethod
    async def _live_invoice(s: AsyncSession, body: InvoiceCreate, payer: str) -> InvoiceRow | None:
        return (await s.execute(select(InvoiceRow).where(
            InvoiceRow.deal_id == body.deal_id, InvoiceRow.kind == body.kind.value,
            InvoiceRow.payer_user_id == payer, InvoiceRow.status.in_(
                [S.PENDING.value, S.AWAITING_PAYMENT.value, S.CONFIRMING.value, S.PAID.value]))
            .order_by(InvoiceRow.created_at.desc()))).scalars().first()

    async def _check_quota(self, s: AsyncSession, payer: str, now: datetime) -> None:
        c = self.settings
        if c.max_open_invoices_per_user > 0:
            open_n = (await s.execute(select(func.count()).select_from(InvoiceRow).where(
                InvoiceRow.payer_user_id == payer,
                InvoiceRow.status.in_([x.value for x in state.OPEN])))).scalar_one()
            if open_n >= c.max_open_invoices_per_user:
                raise TooManyInvoices("Too many open invoices; pay or cancel some first", code="too_many_open_invoices")
        if c.max_invoices_per_user_per_day > 0:
            day_n = (await s.execute(select(func.count()).select_from(InvoiceRow).where(
                InvoiceRow.payer_user_id == payer, InvoiceRow.created_at > now - timedelta(days=1)))).scalar_one()
            if day_n >= c.max_invoices_per_user_per_day:
                raise TooManyInvoices("Daily invoice limit reached; try again later", code="daily_invoice_limit")

    async def prune(self) -> dict[str, int]:
        """Retention. Only inert records: replay rows and delivered outbox events past their window, and attempts of
        invoices that never took money (expired/failed). Open/paid/refunded invoices, the ledger and any pending or dead
        outbox event are never deleted."""
        c, now = self.settings, self.clock()
        out = {"webhook_events": 0, "outbox_delivered": 0, "payment_attempts": 0}
        async with self.sessions() as s:
            if c.webhook_event_retention_days > 0:
                money = select(InvoiceRow.id).where(or_(InvoiceRow.status.in_([S.PAID.value, S.REFUNDED.value]),
                                                        InvoiceRow.status_reason.in_(REVIEW_REASONS)))
                r = await s.execute(delete(WebhookEventRow).where(
                    WebhookEventRow.received_at < now - timedelta(days=c.webhook_event_retention_days),
                    or_(WebhookEventRow.invoice_id.is_(None), WebhookEventRow.invoice_id.not_in(money))))
                out["webhook_events"] = int(r.rowcount or 0)
            if c.outbox_delivered_retention_days > 0:
                r = await s.execute(delete(OutboxEventRow).where(
                    OutboxEventRow.status == "delivered",
                    OutboxEventRow.delivered_at < now - timedelta(days=c.outbox_delivered_retention_days)))
                out["outbox_delivered"] = int(r.rowcount or 0)
            if c.attempt_retention_days > 0:
                dead = select(InvoiceRow.id).where(InvoiceRow.status.in_([S.EXPIRED.value, S.FAILED.value]),
                                                  or_(InvoiceRow.status_reason.is_(None),
                                                      InvoiceRow.status_reason.not_in(REVIEW_REASONS)))
                r = await s.execute(delete(PaymentAttemptRow).where(
                    PaymentAttemptRow.updated_at < now - timedelta(days=c.attempt_retention_days),
                    PaymentAttemptRow.invoice_id.in_(dead)))
                out["payment_attempts"] = int(r.rowcount or 0)
            await s.commit()
        return out

    async def _resolve(self, user: str | None, admin: bool, body: InvoiceCreate) -> tuple[str, str, str, str]:
        """-> (payer, payee, amount string, currency). Non-admins can never choose payer/payee/amount."""
        if admin:
            if not body.payer_user_id or not body.payee:
                raise ValidationFailed("payer_user_id and payee are required for admin invoices",
                                       code="validation_error")
            if body.amount is not None:
                cur = body.amount.currency
                return body.payer_user_id, body.payee, normalize_amount(body.amount.value, cur), cur
            if body.kind == InvoiceKind.COMMISSION and body.commission_basis is not None:
                b = body.commission_basis
                fee = compute_commission(b.subtotal.value, b.subtotal.currency, b.listing_kind,
                                         rates=self._rates(), min_fee_usd=self.settings.min_commission_usd,
                                         usd_rates=DEFAULT_USD_RATES)
                return body.payer_user_id, body.payee, normalize_amount(fee.amount, fee.currency), fee.currency
            raise ValidationFailed("amount (or commission_basis for commission) is required",
                                   code="validation_error")
        if body.has_overrides:
            raise Forbidden("Only admins may set payer, payee, amount or expiry", code="admin_required")
        if user is None:
            raise Forbidden("Authentication required", code="forbidden")
        deal = await self.deals.get_deal(body.deal_id, user)
        if not deal or deal.get("buyer_id") != user:
            raise NotFound("Deal not found", code="deal_not_found")
        if deal.get("status") in DEAD_DEAL_STATES:  # refunded / disputed: new money could never settle it
            raise Conflict("This deal can no longer be paid", code="deal_not_payable",
                           details={"status": deal.get("status")})
        try:
            if body.kind == InvoiceKind.COMMISSION:
                m = deal["commission"]["amount"]
                payee = PLATFORM
            else:
                m = deal["subtotal"]
                payee = str(deal["supplier_user_id"])
            cur = str(m["currency"])
            return user, payee, normalize_amount(Decimal(str(m["amount"])), cur), cur
        except (KeyError, TypeError, ArithmeticError) as exc:
            raise ValidationFailed("Deal has no usable amount", code="deal_invalid") from exc

    async def get_invoice(self, user: str | None, admin: bool, invoice_id: str) -> dict[str, Any]:
        async with self.sessions() as s:
            r = await self._load(s, invoice_id, user, admin)
            return _for_viewer(invoice_dict(r), r, user, admin)

    async def list_invoices(self, user: str | None, admin: bool, *, deal_id: str | None, status: str | None,
                            page: int, size: int) -> dict[str, Any]:
        async with self.sessions() as s:
            await self._expire_due(s)
            conds = []
            if not admin:
                conds.append(or_(InvoiceRow.payer_user_id == user, InvoiceRow.payee == user))
            if deal_id:
                conds.append(InvoiceRow.deal_id == deal_id)
            if status:
                conds.append(InvoiceRow.status == status)
            total = (await s.execute(select(func.count()).select_from(InvoiceRow).where(*conds))).scalar_one()
            rows = (await s.execute(select(InvoiceRow).where(*conds).order_by(
                InvoiceRow.created_at.desc(), InvoiceRow.id).limit(size).offset((page - 1) * size))).scalars().all()
            return {"items": [_for_viewer(invoice_dict(r), r, user, admin) for r in rows], "total": total,
                    "page": page, "page_size": size}

    async def cancel(self, user: str | None, admin: bool, invoice_id: str) -> dict[str, Any]:
        async with self.sessions() as s:
            r = await self._load(s, invoice_id, user, admin)
            if not admin and r.payer_user_id != user:
                raise NotFound("Invoice not found", code="invoice_not_found")
            if S(r.status) not in state.CANCELLABLE:
                raise InvalidTransition("invoice", r.status, "cancel",
                                        allowed=[x.value for x in state.CANCELLABLE], entity_id=r.id)
            await self._move(s, r, S.FAILED, reason="cancelled")
            await s.commit()
            return invoice_dict(r)

    async def refund(self, invoice_id: str) -> dict[str, Any]:
        async with self.sessions() as s:
            r = await self._load(s, invoice_id, None, True)
            await self._move(s, r, S.REFUNDED, reason="refunded")
            await s.commit()
            out = invoice_dict(r)
        await self._drain_quiet()
        return out

    async def list_ledger(self, invoice_id: str) -> dict[str, Any]:
        async with self.sessions() as s:
            rows = (await s.execute(select(LedgerEntryRow).where(LedgerEntryRow.invoice_id == invoice_id)
                                    .order_by(LedgerEntryRow.created_at, LedgerEntryRow.id))).scalars().all()
            return {"items": [ledger_dict(e) for e in rows], "total": len(rows)}

    # ---- outbox: settlement -> rfq ---------------------------------------------------------
    def _backoff(self, attempts: int) -> timedelta:
        return timedelta(seconds=min(self.settings.outbox_backoff_seconds * 2 ** max(attempts - 1, 0), 3600))

    async def drain_outbox(self, limit: int = 100) -> dict[str, int]:
        """Deliver due events oldest-first; per deal the order is kept (a failing/dead event blocks later ones)."""
        out = {"delivered": 0, "retry": 0, "dead": 0}
        async with self.sessions() as s:
            blocked = set((await s.execute(select(OutboxEventRow.deal_id).where(
                OutboxEventRow.status == "dead"))).scalars().all())
            rows = (await s.execute(select(OutboxEventRow).where(OutboxEventRow.status == "pending")
                                    .order_by(OutboxEventRow.id).limit(limit * 4))).scalars().all()
            done = 0
            for row in rows:
                if done >= limit:
                    break
                now = self.clock()
                if row.deal_id in blocked:
                    continue
                if row.next_attempt_at > now:
                    blocked.add(row.deal_id)  # an earlier event of this deal is waiting: keep the order
                    continue
                lease = now + timedelta(seconds=self.settings.outbox_lease_seconds)
                res = await s.execute(update(OutboxEventRow).where(
                    OutboxEventRow.id == row.id, OutboxEventRow.status == "pending",
                    OutboxEventRow.next_attempt_at == row.next_attempt_at).values(next_attempt_at=lease)
                    .execution_options(synchronize_session=False))
                await s.commit()
                if res.rowcount != 1:  # another worker holds it
                    blocked.add(row.deal_id)
                    continue
                done += 1
                row.attempts += 1
                row.updated_at = now
                try:
                    await self.deals.notify_payment_status(row.deal_id, row.payload)
                    row.status, row.delivered_at, row.last_error = "delivered", now, None
                    out["delivered"] += 1
                except NotifyRejected as exc:
                    row.status, row.last_error = "dead", str(exc)[:500]
                    out["dead"] += 1
                    blocked.add(row.deal_id)
                except (UpstreamUnavailable, OSError) as exc:
                    row.last_error = str(exc)[:500] or exc.__class__.__name__
                    if row.attempts >= self.settings.outbox_max_attempts:
                        row.status = "dead"
                        out["dead"] += 1
                    else:
                        row.next_attempt_at = now + self._backoff(row.attempts)
                        out["retry"] += 1
                    blocked.add(row.deal_id)
                await s.commit()
        return out

    async def _drain_quiet(self) -> None:
        """Best-effort immediate delivery after a settlement; failures stay in the outbox for the sweep."""
        with contextlib.suppress(Exception):  # settlement already committed; the outbox keeps the event
            await asyncio.wait_for(self.drain_outbox(20), self.settings.outbox_inline_timeout_seconds)

    @staticmethod
    def _outbox_dict(o: OutboxEventRow) -> dict[str, Any]:
        return {"id": o.id, "event_id": o.event_id, "deal_id": o.deal_id, "status": o.status,
                "attempts": o.attempts, "next_attempt_at": _iso(o.next_attempt_at), "last_error": o.last_error,
                "payload": o.payload, "created_at": _iso(o.created_at), "delivered_at": _iso(o.delivered_at)}

    async def list_outbox(self, status: str | None, page: int, size: int) -> dict[str, Any]:
        async with self.sessions() as s:
            conds = [OutboxEventRow.status == status] if status else []
            total = (await s.execute(select(func.count()).select_from(OutboxEventRow).where(*conds))).scalar_one()
            rows = (await s.execute(select(OutboxEventRow).where(*conds).order_by(OutboxEventRow.id.desc())
                                    .limit(size).offset((page - 1) * size))).scalars().all()
            return {"items": [self._outbox_dict(o) for o in rows], "total": total, "page": page, "page_size": size}

    async def requeue_outbox(self, outbox_id: str) -> dict[str, Any]:
        async with self.sessions() as s:
            o = await s.get(OutboxEventRow, outbox_id)
            if o is None:
                raise NotFound("Outbox event not found", code="outbox_event_not_found")
            if o.status != "dead":
                raise Conflict("Only dead-lettered events can be requeued", code="not_dead")
            o.status, o.attempts, o.next_attempt_at, o.updated_at = "pending", 0, self.clock(), self.clock()
            await s.commit()
            return self._outbox_dict(o)

    # ---- expiry / polling ----------------------------------------------------------------
    async def _expire_due(self, s: AsyncSession) -> int:
        now = self.clock()
        rows = (await s.execute(select(InvoiceRow).where(
            InvoiceRow.status.in_([S.PENDING.value, S.AWAITING_PAYMENT.value]),
            InvoiceRow.expires_at <= now).limit(500))).scalars().all()
        n = 0
        for r in rows:
            try:
                await self._move(s, r, S.EXPIRED, reason="expired")
                n += 1
            except Conflict:  # someone else (e.g. a payment) moved it first
                continue
        if rows:
            await s.commit()
        return n

    async def sweep(self) -> dict[str, int]:
        polled = updated = 0
        if self.provider is not None:
            async with self.sessions() as s:
                ids = (await s.execute(select(InvoiceRow.id).where(
                    InvoiceRow.provider == self.provider.name,
                    InvoiceRow.status.in_([S.AWAITING_PAYMENT.value, S.CONFIRMING.value]))
                    .order_by(InvoiceRow.created_at).limit(200))).scalars().all()
            for iid in ids:
                polled += 1
                async with self.sessions() as s:  # one session per invoice: a refused row never poisons the rest
                    r = await s.get(InvoiceRow, iid)
                    if r is None or r.status not in (S.AWAITING_PAYMENT.value, S.CONFIRMING.value):
                        continue
                    try:
                        obs = await self.provider.poll(TrackedInvoice(
                            r.provider_ref, r.memo, r.pay_address,
                            Decimal(r.pay_amount) if r.pay_amount else None,
                            int(r.created_at.timestamp() * 1000)))
                    except Exception:  # noqa: BLE001 - one bad lookup must not stop the sweep
                        continue
                    try:
                        if obs is None:
                            # reorg safety: a confirming tx that vanished from the chain goes back to awaiting
                            # (nothing is posted to the ledger before PAID)
                            did = r.status == S.CONFIRMING.value and await self._revert_vanished(s, r)
                        else:
                            did = await self._apply_observation(s, r, obs)
                        await s.commit()
                        updated += 1 if did else 0
                    except IntegrityError:  # unique index: this transfer is already bound to another invoice
                        await s.rollback()
        async with self.sessions() as s:
            expired = await self._expire_due(s)
        flagged = await self._scan_late()
        box = await self.drain_outbox()
        pruned = await self.prune()
        return {"pruned": sum(pruned.values()), "expired": expired, "polled": polled, "updated": updated, "late_flagged": flagged, "outbox_delivered": box["delivered"],
                "outbox_retry": box["retry"], "outbox_dead": box["dead"]}

    async def _scan_late(self) -> int:
        """Funds for an invoice that already expired are never silently lost: flag it for manual review."""
        if self.provider is None:
            return 0
        now = self.clock()
        async with self.sessions() as s:
            ids = (await s.execute(select(InvoiceRow.id).where(
                InvoiceRow.provider == self.provider.name, InvoiceRow.status == S.EXPIRED.value,
                InvoiceRow.status_reason == "expired", InvoiceRow.updated_at >= now - LATE_WINDOW)
                .order_by(InvoiceRow.updated_at).limit(200))).scalars().all()
        n = 0
        for iid in ids:
            async with self.sessions() as s:
                r = await s.get(InvoiceRow, iid)
                if r is None or r.status != S.EXPIRED.value or r.status_reason != "expired":
                    continue
                try:
                    obs = await self.provider.poll(TrackedInvoice(
                        r.provider_ref, r.memo, r.pay_address, Decimal(r.pay_amount) if r.pay_amount else None,
                        int(r.created_at.timestamp() * 1000)))
                except Exception:  # noqa: BLE001
                    continue
                if obs is None or (obs.tx_ref and await self._tx_taken(s, r, obs.tx_ref)):
                    continue
                self._flag_review(r, REVIEW_LATE, obs.tx_ref, obs.confirmations)
                await s.commit()
                n += 1
        return n

    def _flag_review(self, r: InvoiceRow, reason: str, tx_ref: str | None, confirmations: int | None) -> None:
        r.status_reason, r.updated_at = reason, self.clock()
        if tx_ref:
            r.tx_ref = tx_ref
        if confirmations is not None:
            r.confirmations = confirmations

    async def list_review(self, page: int, size: int) -> dict[str, Any]:
        async with self.sessions() as s:
            cond = InvoiceRow.status_reason.in_(REVIEW_REASONS)
            total = (await s.execute(select(func.count()).select_from(InvoiceRow).where(cond))).scalar_one()
            rows = (await s.execute(select(InvoiceRow).where(cond).order_by(InvoiceRow.updated_at, InvoiceRow.id)
                                    .limit(size).offset((page - 1) * size))).scalars().all()
            return {"items": [invoice_dict(r) for r in rows], "total": total, "page": page, "page_size": size}

    async def commission_for_deal(self, deal_id: str) -> dict[str, Any]:
        """Platform commission booked for one deal, net of refunds, per currency (from the immutable ledger)."""
        async with self.sessions() as s:
            rows = (await s.execute(select(LedgerEntryRow.direction, LedgerEntryRow.amount, LedgerEntryRow.currency)
                                    .join(InvoiceRow, InvoiceRow.id == LedgerEntryRow.invoice_id)
                                    .where(InvoiceRow.deal_id == deal_id,
                                           LedgerEntryRow.account == "revenue:commission"))).all()
        earned: dict[str, Decimal] = {}
        refunded: dict[str, Decimal] = {}
        for direction, amount, cur in rows:
            bucket = earned if direction == Direction.CREDIT.value else refunded
            bucket[cur] = bucket.get(cur, Decimal(0)) + Decimal(amount)
        items = [{"currency": c, "earned": format(earned.get(c, Decimal(0)), "f"),
                  "refunded": format(refunded.get(c, Decimal(0)), "f"),
                  "net": format(earned.get(c, Decimal(0)) - refunded.get(c, Decimal(0)), "f")}
                 for c in sorted(set(earned) | set(refunded))]
        return {"deal_id": deal_id, "items": items}

    async def _revert_vanished(self, s: AsyncSession, r: InvoiceRow) -> bool:
        try:
            await self._move(s, r, S.AWAITING_PAYMENT, reason="tx_disappeared", confirmations=0)
        except Conflict:
            return False
        r.tx_ref = None
        # the payer did pay once: give the re-broadcast/re-mined transfer a grace window before expiry applies
        r.expires_at = max(r.expires_at, self.clock() + REORG_GRACE)
        return True

    @staticmethod
    async def _tx_taken(s: AsyncSession, r: InvoiceRow, tx_ref: str) -> bool:
        return (await s.execute(select(InvoiceRow.id).where(
            InvoiceRow.tx_ref == tx_ref, InvoiceRow.id != r.id, InvoiceRow.provider == r.provider,
            or_(InvoiceRow.status.in_([S.CONFIRMING.value, S.PAID.value]),
                InvoiceRow.status_reason == REVIEW_LATE)).limit(1))).first() is not None

    async def _apply_observation(self, s: AsyncSession, r: InvoiceRow, obs: Observation) -> bool:
        target = S.PAID if obs.status == "paid" else S.CONFIRMING
        cur = S(r.status)
        if obs.tx_ref and await self._tx_taken(s, r, obs.tx_ref):  # one transfer settles at most one invoice
            return False
        if cur == target:
            changed = obs.confirmations != r.confirmations
            r.confirmations = obs.confirmations
            return changed
        if not state.can(cur, target):
            return False
        try:
            await self._move(s, r, target, tx_ref=obs.tx_ref, confirmations=obs.confirmations)
        except Conflict:
            return False
        return True

    # ---- webhooks ------------------------------------------------------------------------
    async def handle_webhook(self, provider: str, raw: bytes, signature: str | None) -> dict[str, Any]:
        if provider not in KNOWN_PROVIDERS:
            raise NotFound("Unknown provider", code="unknown_provider")
        secret = self.settings.webhook_secret(provider)
        if not secret:
            raise _WebhookOff()
        now = self.clock()
        webhooks.verify(secret, raw, signature, now_ts=int(now.timestamp()),
                        tolerance=self.settings.webhook_tolerance_seconds)
        try:
            ev = WebhookEvent.model_validate(json.loads(raw))
        except (ValueError, ValidationError) as exc:
            raise _BadEvent() from exc
        async with self.sessions() as s:
            if await s.get(WebhookEventRow, (provider, ev.event_id)) is not None:
                return {"status": "duplicate", "invoice_id": None, "invoice_status": None}
            r = await self._find_for_event(s, provider, ev)
            if r is None:
                raise NotFound("Invoice not found", code="invoice_not_found")  # not recorded: provider may retry
            rid = r.id
            if EVENT_TARGET[ev.type] in (S.CONFIRMING, S.PAID):
                await self._expire_if_due(s, r)  # money arriving past the TTL is reviewed, never auto-settled
            try:
                outcome = await self._apply_event(s, r, ev)
                s.add(WebhookEventRow(provider=provider, event_id=ev.event_id, invoice_id=rid,
                                      outcome=outcome, received_at=now))
                await s.commit()
            except IntegrityError:
                await s.rollback()
                if await s.get(WebhookEventRow, (provider, ev.event_id)) is not None:  # concurrent same event
                    return {"status": "duplicate", "invoice_id": None, "invoice_status": None}
                # a unique index refused the transition (transfer/amount already bound to another invoice)
                r = await s.get(InvoiceRow, rid)
                s.add(WebhookEventRow(provider=provider, event_id=ev.event_id, invoice_id=rid,
                                      outcome="ignored", received_at=now))
                try:
                    await s.commit()
                except IntegrityError:
                    await s.rollback()
                    return {"status": "duplicate", "invoice_id": None, "invoice_status": None}
                return {"status": "ignored", "invoice_id": r.id if r else None,
                        "invoice_status": r.status if r else None}
            res = {"status": outcome, "invoice_id": r.id, "invoice_status": r.status}
        if outcome == "applied":
            await self._drain_quiet()
        return res

    async def _find_for_event(self, s: AsyncSession, provider: str, ev: WebhookEvent) -> InvoiceRow | None:
        if ev.invoice_id:
            r = await s.get(InvoiceRow, ev.invoice_id)
        elif ev.provider_ref:
            r = (await s.execute(select(InvoiceRow).where(InvoiceRow.provider_ref == ev.provider_ref,
                                                          InvoiceRow.provider == provider))).scalars().first()
        else:
            r = None
        return r if r is not None and r.provider == provider else None

    async def _apply_event(self, s: AsyncSession, r: InvoiceRow, ev: WebhookEvent) -> str:
        target = EVENT_TARGET[ev.type]
        if r.provider == "usdt_tron" and target in (S.CONFIRMING, S.PAID):
            return "ignored"  # on-chain settlement is proven only by our own explorer poll, never by a callback
        cur = S(r.status)
        if target == S.PAID and ev.amount is not None:
            want = Decimal(r.pay_amount or r.amount)
            if ev.amount.value != want or ev.amount.currency != (r.pay_currency or r.currency):
                if cur in (S.PENDING, S.AWAITING_PAYMENT, S.CONFIRMING, S.EXPIRED, S.FAILED):
                    # wrong amount never settles, but it is money we must not lose track of
                    self._flag_review(r, REVIEW_AMOUNT, ev.tx_ref if cur not in state.OPEN else None, None)
                    return "review"
                return "ignored"
        if target in (S.CONFIRMING, S.PAID) and cur in (S.EXPIRED, S.FAILED):
            if ev.tx_ref and await self._tx_taken(s, r, ev.tx_ref):
                return "ignored"
            self._flag_review(r, REVIEW_LATE, ev.tx_ref, ev.confirmations)  # paid after expiry / cancel
            return "review"
        if cur == target:
            return "ignored"
        if not state.can(cur, target):
            return "ignored"
        if ev.tx_ref and target in (S.CONFIRMING, S.PAID) and await self._tx_taken(s, r, ev.tx_ref):
            return "ignored"  # one transfer can settle at most one invoice
        try:
            await self._move(s, r, target, reason=f"webhook:{ev.type}" if target in (S.FAILED, S.EXPIRED) else None,
                             tx_ref=ev.tx_ref, confirmations=ev.confirmations)
        except Conflict:
            return "ignored"
        return "applied"


class _Disabled(Conflict):
    status_code = 503
    default_code = "provider_disabled"

    def __init__(self) -> None:
        super().__init__("Payments are switched off (FF_PAYMENTS_PROVIDER=off)")


class _WebhookOff(Conflict):
    status_code = 503
    default_code = "webhook_not_configured"

    def __init__(self) -> None:
        super().__init__("Webhook secret is not configured for this provider")


class _BadEvent(Conflict):
    status_code = 400
    default_code = "invalid_event"

    def __init__(self) -> None:
        super().__init__("Malformed webhook event")
