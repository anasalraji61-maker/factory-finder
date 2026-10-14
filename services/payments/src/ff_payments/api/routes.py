"""Thin FastAPI routers (all logic lives in PaymentsService)."""

from __future__ import annotations

import hmac
from typing import Annotated, Any, NamedTuple

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from ff_payments.domain.enums import InvoiceStatus
from ff_payments.domain.errors import Forbidden, Unauthenticated
from ff_payments.schemas import InvoiceCreate
from ff_payments.service import PaymentsService

router = APIRouter(prefix="/v1")


class Actor(NamedTuple):
    user: str | None
    admin: bool


def svc(request: Request) -> PaymentsService:
    return request.app.state.service


Svc = Annotated[PaymentsService, Depends(svc)]


def _is_admin(request: Request, token: str | None) -> bool:
    secret = request.app.state.service.settings.admin_token
    if secret is None or not token:
        return False
    return hmac.compare_digest(token.encode(), secret.get_secret_value().encode())


def actor(request: Request, x_user_id: Annotated[str | None, Header()] = None,
          x_admin_token: Annotated[str | None, Header()] = None) -> Actor:
    admin = _is_admin(request, x_admin_token)
    user = x_user_id.strip() if x_user_id and x_user_id.strip() else None
    if user is None and not admin:
        raise Unauthenticated("X-User-Id header is required")
    return Actor(user, admin)


def admin_only(request: Request, x_admin_token: Annotated[str | None, Header()] = None) -> None:
    if not _is_admin(request, x_admin_token):
        raise Forbidden("Admin only", code="admin_required")


Who = Annotated[Actor, Depends(actor)]
Page = Annotated[int, Query(ge=1)]
Size = Annotated[int, Query(ge=1, le=100)]


@router.post("/invoices", status_code=201)
async def create_invoice(body: InvoiceCreate, who: Who, s: Svc, response: Response) -> dict[str, Any]:
    inv, created = await s.create_invoice(who.user, who.admin, body)
    if not created:
        response.status_code = 200
    return inv


@router.get("/invoices")
async def list_invoices(who: Who, s: Svc, deal_id: str | None = None, status: InvoiceStatus | None = None,
                        page: Page = 1, page_size: Size = 20) -> dict[str, Any]:
    return await s.list_invoices(who.user, who.admin, deal_id=deal_id,
                                 status=status.value if status else None, page=page, size=page_size)


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, who: Who, s: Svc) -> dict[str, Any]:
    return await s.get_invoice(who.user, who.admin, invoice_id)


@router.post("/invoices/{invoice_id}/cancel")
async def cancel_invoice(invoice_id: str, who: Who, s: Svc) -> dict[str, Any]:
    return await s.cancel(who.user, who.admin, invoice_id)


@router.post("/invoices/{invoice_id}/refund", dependencies=[Depends(admin_only)])
async def refund_invoice(invoice_id: str, s: Svc) -> dict[str, Any]:
    return await s.refund(invoice_id)


@router.get("/ledger", dependencies=[Depends(admin_only)])
async def list_ledger(s: Svc, invoice_id: Annotated[str, Query(min_length=1)]) -> dict[str, Any]:
    return await s.list_ledger(invoice_id)


@router.post("/payments/sweep", dependencies=[Depends(admin_only)])
async def sweep(s: Svc) -> dict[str, int]:
    return await s.sweep()


@router.post("/payments/webhooks/{provider}")
async def webhook(provider: str, request: Request, s: Svc,
                  x_ff_signature: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    return await s.handle_webhook(provider, await request.body(), x_ff_signature)
