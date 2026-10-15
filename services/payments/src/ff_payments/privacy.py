"""Account export / erasure (internal token only; see docs/decisions/account-deletion.md).

The ledger, invoices, attempts, webhook events and outbox are financial/audit records and are never altered or deleted.
Export lists the user's invoices; erasure only blanks the free-text ``user_memo`` the payer typed.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import or_, select, update

from ff_payments.db import InvoiceRow

router = APIRouter(prefix="/v1/internal")
CAP = 500


@router.post("/users/{user_id}/export")
async def export_user(user_id: str, request: Request) -> dict:
    eng = request.app.state.service.engine
    async with eng.connect() as c:
        rows = (await c.execute(
            select(InvoiceRow.id, InvoiceRow.deal_id, InvoiceRow.kind, InvoiceRow.amount, InvoiceRow.currency,
                   InvoiceRow.status, InvoiceRow.user_memo, InvoiceRow.paid_at, InvoiceRow.created_at)
            .where(or_(InvoiceRow.payer_user_id == user_id, InvoiceRow.payee == user_id)).limit(CAP + 1)
        )).mappings().all()  # fmt: skip
    return {
        "service": "payments", "user_id": user_id, "truncated": len(rows) > CAP,
        "data": {"invoices": [{**r, "paid_at": r["paid_at"].isoformat() if r["paid_at"] else None,
                               "created_at": r["created_at"].isoformat()} for r in rows[:CAP]]},
    }  # fmt: skip


@router.delete("/users/{user_id}/data")
async def erase_user(user_id: str, request: Request) -> dict:
    eng = request.app.state.service.engine
    async with eng.begin() as c:
        res = await c.execute(
            update(InvoiceRow).where(InvoiceRow.payer_user_id == user_id, InvoiceRow.user_memo.is_not(None)).values(user_memo=None)
        )
    return {"service": "payments", "user_id": user_id, "status": "done", "counts": {"memos_cleared": int(res.rowcount or 0)},
            "retained": ["invoices", "ledger_entries", "payment_attempts", "webhook_events", "outbox_events"]}  # fmt: skip
