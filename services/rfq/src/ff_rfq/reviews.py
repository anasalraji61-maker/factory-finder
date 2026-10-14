"""Verified-deal reviews: one per deal, written by the buyer, answered once by the verified supplier."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ff_rfq.db import DealRow, OfferRow, ReviewEventRow, ReviewReportRow, ReviewRow
from ff_rfq.domain.enums import DealStatus
from ff_rfq.domain.errors import Conflict, Forbidden, NotFound, RateLimited
from ff_rfq.domain.review_text import average, clean_text, reviewer_display
from ff_rfq.schemas import ReplyCreate, ReportCreate, ReviewCreate

REVIEWABLE = (DealStatus.PAID.value, DealStatus.IN_FULFILMENT.value, DealStatus.COMPLETED.value)
EDIT_WINDOW = timedelta(hours=24)
REPORTS_PER_HOUR = 10
SUBS = ("quality", "communication", "shipping")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _page(items: list, total: int, p: int, size: int) -> dict[str, Any]:
    return {"items": items, "total": total, "page": p, "page_size": size}


def _snapshot(r: ReviewRow) -> dict[str, Any]:
    return {"rating": r.rating, "title": r.title, "text": r.text, "quality": r.quality,
            "communication": r.communication, "shipping": r.shipping}


def review_dict(r: ReviewRow, viewer: str | None = None) -> dict[str, Any]:
    mine = viewer is not None and viewer == r.buyer_id
    return {
        "id": r.id, "supplier_ref": r.supplier_ref, "rating": r.rating,
        "sub_ratings": {k: getattr(r, k) for k in SUBS},
        "title": r.title, "text": r.text, "reviewer": r.reviewer_display, "verified_purchase": True,
        "edited": r.edited_at is not None,
        "reply": {"text": r.reply_text, "created_at": _iso(r.replied_at)} if r.reply_text else None,
        "mine": mine, "editable_until": _iso(r.created_at + EDIT_WINDOW) if mine else None,
        "flagged_for_review": r.flagged_for_review if mine else None,
        "created_at": _iso(r.created_at), "updated_at": _iso(r.updated_at),
    }


class ReviewService:
    def __init__(self, engine: AsyncEngine, clock: Callable[[], datetime]) -> None:
        self.clock = clock
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    @staticmethod
    def _event(s: AsyncSession, review_id: str, action: str, actor: str, now: datetime,
               snapshot: dict | None = None) -> None:
        s.add(ReviewEventRow(id=_id("rve"), review_id=review_id, action=action, actor_id=actor,
                             snapshot=snapshot, created_at=now))

    @staticmethod
    async def _published(s: AsyncSession, review_id: str) -> ReviewRow:
        r = await s.get(ReviewRow, review_id)
        if r is None or r.status != "published":
            raise NotFound("Review not found")
        return r

    # ---- buyer ---------------------------------------------------------------------------
    async def create(self, user: str, deal_id: str, body: ReviewCreate, display_name: str | None) -> dict[str, Any]:
        now = self.clock()
        try:
            async with self._sessions() as s, s.begin():
                deal = await s.get(DealRow, deal_id)
                if deal is None or user not in (deal.buyer_id, deal.supplier_user_id):
                    raise NotFound("Deal not found")
                if deal.buyer_id != user:
                    raise Forbidden("Only the buyer of a deal can review it")
                if deal.status not in REVIEWABLE:
                    raise Conflict("The deal must be paid before it can be reviewed", code="deal_not_reviewable",
                                   details={"status": deal.status})
                offer = await s.get(OfferRow, deal.offer_id)
                if offer is None or not offer.supplier_ref:
                    raise Conflict("The supplier of this deal is not a verified supplier", code="supplier_unverified")
                if await s.scalar(select(ReviewRow.id).where(ReviewRow.deal_id == deal.id)):
                    raise Conflict("This deal already has a review", code="review_already_exists")
                title = clean_text(body.title, "title", 80)
                text = clean_text(body.text, "text", 1000)
                subs = body.sub_ratings.model_dump() if body.sub_ratings else {}
                row = ReviewRow(
                    id=_id("rev"), deal_id=deal.id, buyer_id=user, supplier_ref=offer.supplier_ref,
                    reviewer_display=reviewer_display(display_name), rating=body.rating,
                    quality=subs.get("quality"), communication=subs.get("communication"),
                    shipping=subs.get("shipping"), title=title, text=text, status="published",
                    flagged_for_review=False, created_at=now, updated_at=now)
                s.add(row)
                await s.flush()
                self._event(s, row.id, "created", user, now, _snapshot(row))
        except IntegrityError as e:  # concurrent duplicate (unique deal_id)
            raise Conflict("This deal already has a review", code="review_already_exists") from e
        return review_dict(row, user)

    async def _own(self, s: AsyncSession, user: str, review_id: str, now: datetime) -> ReviewRow:
        r = await self._published(s, review_id)
        if r.buyer_id != user:
            raise Forbidden("Only the author can change this review")
        if now > r.created_at + EDIT_WINDOW:
            raise Conflict("Reviews can only be edited or deleted within 24 hours", code="review_window_closed",
                           details={"editable_until": _iso(r.created_at + EDIT_WINDOW)})
        return r

    async def update(self, user: str, review_id: str, body: ReviewCreate) -> dict[str, Any]:
        now = self.clock()
        async with self._sessions() as s, s.begin():
            r = await self._own(s, user, review_id, now)
            title = clean_text(body.title, "title", 80)
            text = clean_text(body.text, "text", 1000)
            self._event(s, r.id, "edited", user, now, _snapshot(r))  # previous values
            subs = body.sub_ratings.model_dump() if body.sub_ratings else {}
            r.rating, r.title, r.text = body.rating, title, text
            r.quality, r.communication, r.shipping = (subs.get(k) for k in SUBS)
            r.edited_at = r.updated_at = now
            return review_dict(r, user)

    async def delete(self, user: str, review_id: str) -> dict[str, Any]:
        now = self.clock()
        async with self._sessions() as s, s.begin():
            r = await self._own(s, user, review_id, now)
            self._event(s, r.id, "deleted", user, now, _snapshot(r))
            r.status, r.deleted_at, r.updated_at = "deleted", now, now
            return {"id": r.id, "status": "deleted"}

    # ---- supplier / community ------------------------------------------------------------
    async def reply(self, user: str, supplier_id: str | None, review_id: str, body: ReplyCreate) -> dict[str, Any]:
        now = self.clock()
        async with self._sessions() as s, s.begin():
            r = await self._published(s, review_id)
            if not supplier_id or supplier_id != r.supplier_ref:
                raise Forbidden("Only the verified supplier of this deal can reply")
            if r.reply_text:
                raise Conflict("This review already has a reply", code="reply_already_exists")
            text = clean_text(body.text, "text", 500)
            if text is None:
                from ff_rfq.domain.errors import ValidationFailed
                raise ValidationFailed("text must not be empty", code="empty_text", details={"field": "text"})
            r.reply_text, r.reply_by, r.replied_at, r.updated_at = text, user, now, now
            self._event(s, r.id, "replied", user, now)
            return review_dict(r, None)

    async def report(self, user: str, review_id: str, body: ReportCreate) -> dict[str, Any]:
        now = self.clock()
        async with self._sessions() as s, s.begin():
            r = await self._published(s, review_id)
            if r.buyer_id == user:
                raise Forbidden("You cannot report your own review")
            if await s.scalar(select(ReviewReportRow.id).where(
                    ReviewReportRow.review_id == r.id, ReviewReportRow.reporter_id == user)):
                return {"id": r.id, "flagged_for_review": True, "already_reported": True}
            recent = (await s.execute(select(func.count()).select_from(ReviewReportRow).where(
                ReviewReportRow.reporter_id == user, ReviewReportRow.created_at > now - timedelta(hours=1)))).scalar_one()
            if recent >= REPORTS_PER_HOUR:
                raise RateLimited("Too many reports, try again later", details={"limit_per_hour": REPORTS_PER_HOUR})
            note = clean_text(body.note, "note", 300)
            s.add(ReviewReportRow(id=_id("rvr"), review_id=r.id, reporter_id=user, reason=body.reason,
                                  note=note, created_at=now))
            r.flagged_for_review = True  # never auto-hidden: a moderator decides
            self._event(s, r.id, "reported", user, now, {"reason": body.reason})
            return {"id": r.id, "flagged_for_review": True, "already_reported": False}

    # ---- public reads --------------------------------------------------------------------
    async def list_for_supplier(self, supplier_ref: str, *, sort: str, p: int, size: int,
                                viewer: str | None) -> dict[str, Any]:
        cond = (ReviewRow.supplier_ref == supplier_ref, ReviewRow.status == "published")
        order = ([ReviewRow.rating.desc(), ReviewRow.created_at.desc(), ReviewRow.id] if sort == "rating"
                 else [ReviewRow.created_at.desc(), ReviewRow.id])
        async with self._sessions() as s, s.begin():
            total = (await s.execute(select(func.count()).select_from(ReviewRow).where(*cond))).scalar_one()
            rows = (await s.execute(select(ReviewRow).where(*cond).order_by(*order)
                                    .offset((p - 1) * size).limit(size))).scalars().all()
            return _page([review_dict(r, viewer) for r in rows], total, p, size)

    async def summary(self, supplier_ref: str) -> dict[str, Any]:
        cond = (ReviewRow.supplier_ref == supplier_ref, ReviewRow.status == "published")
        async with self._sessions() as s, s.begin():
            rows = (await s.execute(select(ReviewRow.rating, func.count()).where(*cond)
                                    .group_by(ReviewRow.rating))).all()
            hist = {str(i): 0 for i in range(1, 6)}
            for rating, n in rows:
                hist[str(rating)] = n
            count = sum(hist.values())
            total = sum(int(k) * v for k, v in hist.items())
            subs: dict[str, str | None] = {}
            for k in SUBS:
                col = getattr(ReviewRow, k)
                n, t = (await s.execute(select(func.count(col), func.coalesce(func.sum(col), 0)).where(*cond))).one()
                subs[k] = average(int(t), int(n))
            done = (await s.execute(select(func.count()).select_from(DealRow).join(
                OfferRow, DealRow.offer_id == OfferRow.id).where(
                OfferRow.supplier_ref == supplier_ref, DealRow.status == DealStatus.COMPLETED.value))).scalar_one()
        return {"supplier_ref": supplier_ref, "count": count, "average": average(total, count),
                "histogram": hist, "sub_ratings": subs, "completed_deals": done}
