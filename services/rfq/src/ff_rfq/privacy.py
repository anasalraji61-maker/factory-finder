"""Account export / erasure (internal token only; see docs/decisions/account-deletion.md).

Personal free text is scrubbed (request title/description/attachments, offer notes, review text, replies, report notes,
audit snapshots). Financial records required for audit are retained untouched: deals, deal_events, and the money fields of
offers. User ids stay (they are pseudonymous once the gateway has scrubbed the account).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ff_rfq.db import DealRow, OfferRow, RequestRow, ReviewEventRow, ReviewReportRow, ReviewRow

CAP = 500
GONE = "[deleted]"


def _d(row, keys) -> dict:
    return {k: (getattr(row, k).isoformat() if hasattr(getattr(row, k), "isoformat") else getattr(row, k)) for k in keys}


async def export_user(engine: AsyncEngine, user_id: str) -> dict:
    async with AsyncSession(engine) as c:
        async def q(model, cond):
            return (await c.scalars(select(model).where(cond).limit(CAP + 1))).all()

        reqs = await q(RequestRow, RequestRow.owner_id == user_id)
        offers = await q(OfferRow, OfferRow.supplier_user_id == user_id)
        deals = await q(DealRow, or_(DealRow.buyer_id == user_id, DealRow.supplier_user_id == user_id))
        revs = await q(ReviewRow, ReviewRow.buyer_id == user_id)
    return {
        "truncated": any(len(x) > CAP for x in (reqs, offers, deals, revs)),
        "data": {
            "requests": [_d(r, ("id", "kind", "title", "description", "quantity", "unit", "condition", "target_amount", "target_currency", "destination", "visibility", "status", "created_at")) for r in reqs[:CAP]],
            "offers": [_d(o, ("id", "request_id", "supplier_name", "price_amount", "price_currency", "moq", "lead_time_days", "incoterm", "notes", "status", "created_at")) for o in offers[:CAP]],
            "deals": [_d(x, ("id", "request_id", "offer_id", "kind", "quantity", "unit_price", "currency", "subtotal", "commission_rate", "commission_amount", "status", "created_at")) for x in deals[:CAP]],
            "reviews": [_d(r, ("id", "deal_id", "supplier_ref", "rating", "title", "text", "status", "created_at")) for r in revs[:CAP]],
        },
    }  # fmt: skip


async def erase_user(engine: AsyncEngine, user_id: str) -> dict[str, int]:
    t = datetime.now(UTC)
    n: dict[str, int] = {}
    async with engine.begin() as c:
        # requests: awarded ones back a deal (kept as-is); everything else is cancelled and scrubbed
        deal_reqs = select(DealRow.request_id)
        r = await c.execute(
            update(RequestRow)
            .where(RequestRow.owner_id == user_id, RequestRow.id.not_in(deal_reqs))
            .values(title=GONE, description=None, attachments=[], destination=None, updated_at=t)
        )  # fmt: skip
        n["requests_scrubbed"] = int(r.rowcount or 0)
        await c.execute(
            update(RequestRow)
            .where(RequestRow.owner_id == user_id, RequestRow.status.in_(("open", "negotiating")), RequestRow.id.not_in(deal_reqs))
            .values(status="cancelled")
        )  # fmt: skip
        # offers: notes always go, pending ones are withdrawn; the name stays on accepted offers (audit)
        await c.execute(update(OfferRow).where(OfferRow.supplier_user_id == user_id, OfferRow.status == "active").values(status="withdrawn", updated_at=t))
        r = await c.execute(update(OfferRow).where(OfferRow.supplier_user_id == user_id).values(notes=None))
        n["offers_scrubbed"] = int(r.rowcount or 0)
        await c.execute(
            update(OfferRow).where(OfferRow.supplier_user_id == user_id, OfferRow.status != "accepted").values(supplier_name=GONE)
        )
        # reviews: kept as deleted rows (audit trail), text and display name gone
        mine = [x[0] for x in (await c.execute(select(ReviewRow.id).where(ReviewRow.buyer_id == user_id))).all()]
        r = await c.execute(
            update(ReviewRow).where(ReviewRow.buyer_id == user_id, ReviewRow.text.is_not(None) | ReviewRow.title.is_not(None) | (ReviewRow.status != "deleted") | (ReviewRow.reviewer_display != GONE))
            .values(title=None, text=None, reviewer_display=GONE, status="deleted", deleted_at=t, updated_at=t)
        )  # fmt: skip
        n["reviews_scrubbed"] = int(r.rowcount or 0)
        await c.execute(update(ReviewRow).where(ReviewRow.reply_by == user_id).values(reply_text=None))
        if mine:
            await c.execute(update(ReviewEventRow).where(ReviewEventRow.review_id.in_(mine)).values(snapshot=None))
            await c.execute(update(ReviewReportRow).where(ReviewReportRow.review_id.in_(mine)).values(note=None))
        await c.execute(update(ReviewReportRow).where(ReviewReportRow.reporter_id == user_id).values(note=None))
    return n
