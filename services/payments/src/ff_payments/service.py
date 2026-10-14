"""PaymentsService: all business logic (routes stay thin). Money = Decimal everywhere, strings at rest."""

from __future__ import annotations

import base64
import json
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ff_payments import webhooks
from ff_payments.clients.deals import DealClient
from ff_payments.config import Settings
from ff_payments.db import Base, InvoiceRow, LedgerEntryRow, PaymentAttemptRow, WebhookEventRow
from ff_payments.domain import ledger, state
from ff_payments.domain.commission import DEFAULT_USD_RATES, compute_commission
from ff_payments.domain.enums import Direction, InvoiceKind, InvoiceStatus, ListingKind
from ff_payments.domain.errors import (
    Conflict,
    Forbidden,
    InvalidTransition,
    NotFound,
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
            await self._move(s, r, S.EXPIRED, reason="expired")
            await s.commit()

    async def _move(self, s: AsyncSession, r: InvoiceRow, target: S, *, reason: str | None = None,
                    tx_ref: str | None = None, confirmations: int | None = None) -> None:
        """Apply a validated transition (and its ledger effect). Caller commits."""
        now = self.clock()
        state.require(S(r.status), target, r.id)
        r.status, r.updated_at = target.value, now
        if reason:
            r.status_reason = reason
        if tx_ref:
            r.tx_ref = tx_ref
        if confirmations is not None:
            r.confirmations = confirmations
        if target == S.PAID:
            r.paid_at = now
            await self._post(s, r, ledger.payment_legs(provider=r.provider, payee=r.payee, kind=r.kind,
                                                       amount=Decimal(r.amount), currency=r.currency), "payment")
        elif target == S.REFUNDED:
            rows = (await s.execute(select(LedgerEntryRow).where(
                LedgerEntryRow.invoice_id == r.id, LedgerEntryRow.reason == "payment"))).scalars().all()
            legs = [ledger.Leg(e.account, Direction(e.direction), Decimal(e.amount), e.currency) for e in rows]
            await self._post(s, r, ledger.refund_legs(legs), "refund")
        att = (await s.execute(select(PaymentAttemptRow).where(PaymentAttemptRow.invoice_id == r.id)
                               .order_by(PaymentAttemptRow.created_at.desc()).limit(1))).scalar_one_or_none()
        if att and target in (S.CONFIRMING, S.PAID, S.FAILED):
            att.status = {S.CONFIRMING: "confirming", S.PAID: "confirmed", S.FAILED: "failed"}[target]
            att.tx_ref, att.updated_at = tx_ref or att.tx_ref, now

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
        async with self.sessions() as s:
            existing = (await s.execute(select(InvoiceRow).where(
                InvoiceRow.deal_id == body.deal_id, InvoiceRow.kind == body.kind.value,
                InvoiceRow.payer_user_id == payer, InvoiceRow.status.in_(
                    [S.PENDING.value, S.AWAITING_PAYMENT.value, S.CONFIRMING.value, S.PAID.value]))
                .order_by(InvoiceRow.created_at.desc()))).scalars().first()
            if existing is not None:
                await self._expire_if_due(s, existing)
                if existing.status != S.EXPIRED.value:
                    return invoice_dict(existing), False
            invoice_id = _uid("inv")
            memo = _new_memo()
            taken = frozenset((await s.execute(select(InvoiceRow.pay_amount).where(
                InvoiceRow.provider == self.provider.name, InvoiceRow.pay_amount.is_not(None),
                InvoiceRow.status.in_([S.AWAITING_PAYMENT.value, S.CONFIRMING.value])))).scalars().all())
            charge = await self.provider.create(InvoiceSpec(invoice_id, memo, Decimal(amount), currency, taken))
            row = InvoiceRow(
                id=invoice_id, deal_id=body.deal_id, payer_user_id=payer, payee=payee, kind=body.kind.value,
                amount=amount, currency=currency, status=S.PENDING.value, expires_at=now + timedelta(minutes=ttl),
                provider=self.provider.name, memo=memo, user_memo=body.memo, confirmations=0,
                created_at=now, updated_at=now)
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
            return invoice_dict(row), True

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
            return invoice_dict(await self._load(s, invoice_id, user, admin))

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
            return {"items": [invoice_dict(r) for r in rows], "total": total, "page": page, "page_size": size}

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
            return invoice_dict(r)

    async def list_ledger(self, invoice_id: str) -> dict[str, Any]:
        async with self.sessions() as s:
            rows = (await s.execute(select(LedgerEntryRow).where(LedgerEntryRow.invoice_id == invoice_id)
                                    .order_by(LedgerEntryRow.created_at, LedgerEntryRow.id))).scalars().all()
            return {"items": [ledger_dict(e) for e in rows], "total": len(rows)}

    # ---- expiry / polling ----------------------------------------------------------------
    async def _expire_due(self, s: AsyncSession) -> int:
        now = self.clock()
        rows = (await s.execute(select(InvoiceRow).where(
            InvoiceRow.status.in_([S.PENDING.value, S.AWAITING_PAYMENT.value]),
            InvoiceRow.expires_at <= now).limit(500))).scalars().all()
        for r in rows:
            await self._move(s, r, S.EXPIRED, reason="expired")
        if rows:
            await s.commit()
        return len(rows)

    async def sweep(self) -> dict[str, int]:
        polled = updated = 0
        async with self.sessions() as s:
            if self.provider is not None:
                rows = (await s.execute(select(InvoiceRow).where(
                    InvoiceRow.provider == self.provider.name,
                    InvoiceRow.status.in_([S.AWAITING_PAYMENT.value, S.CONFIRMING.value]))
                    .order_by(InvoiceRow.created_at).limit(200))).scalars().all()
                for r in rows:
                    polled += 1
                    try:
                        obs = await self.provider.poll(TrackedInvoice(
                            r.provider_ref, r.memo, r.pay_address,
                            Decimal(r.pay_amount) if r.pay_amount else None,
                            int(r.created_at.timestamp() * 1000)))
                    except Exception:  # noqa: BLE001 - one bad lookup must not stop the sweep
                        continue
                    if obs is not None and await self._apply_observation(s, r, obs):
                        updated += 1
                await s.commit()
            expired = await self._expire_due(s)
        return {"expired": expired, "polled": polled, "updated": updated}

    async def _apply_observation(self, s: AsyncSession, r: InvoiceRow, obs: Observation) -> bool:
        target = S.PAID if obs.status == "paid" else S.CONFIRMING
        cur = S(r.status)
        if cur == target:
            changed = obs.confirmations != r.confirmations
            r.confirmations = obs.confirmations
            return changed
        if not state.can(cur, target):
            return False
        await self._move(s, r, target, tx_ref=obs.tx_ref, confirmations=obs.confirmations)
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
            outcome = await self._apply_event(s, r, ev)
            s.add(WebhookEventRow(provider=provider, event_id=ev.event_id, invoice_id=r.id,
                                  outcome=outcome, received_at=now))
            try:
                await s.commit()
            except IntegrityError:  # concurrent delivery of the same event
                await s.rollback()
                return {"status": "duplicate", "invoice_id": None, "invoice_status": None}
            return {"status": outcome, "invoice_id": r.id, "invoice_status": r.status}

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
        if target == S.PAID and ev.amount is not None:
            want = Decimal(r.pay_amount or r.amount)
            if ev.amount.value != want or ev.amount.currency != (r.pay_currency or r.currency):
                return "ignored"  # wrong amount never settles an invoice
        cur = S(r.status)
        if cur == target:
            return "ignored"
        if not state.can(cur, target):
            return "ignored"
        await self._move(s, r, target, reason=f"webhook:{ev.type}" if target in (S.FAILED, S.EXPIRED) else None,
                         tx_ref=ev.tx_ref, confirmations=ev.confirmations)
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
