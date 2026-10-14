"""Thin FastAPI routers (all logic lives in RfqService)."""

from __future__ import annotations

import hmac
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, Path, Query, Request

from ff_rfq.deals import DealService
from ff_rfq.domain.enums import DealStatus, ListingKind, OfferStatus, RequestStatus
from ff_rfq.domain.errors import Unauthenticated
from ff_rfq.reviews import ReviewService
from ff_rfq.schemas import (
    OfferCreate,
    PaymentStatusCallback,
    ReplyCreate,
    ReportCreate,
    RequestCreate,
    ReviewCreate,
)
from ff_rfq.service import RfqService

router = APIRouter(prefix="/v1")


def current_user(x_user_id: Annotated[str | None, Header()] = None) -> str:
    if not x_user_id or not x_user_id.strip():
        raise Unauthenticated("X-User-Id header is required")
    return x_user_id.strip()


def verified_supplier(x_supplier_id: Annotated[str | None, Header()] = None) -> str | None:
    """Gateway-verified supplier id (only forwarded for admin-verified claims); never taken from the body."""
    return x_supplier_id.strip() if x_supplier_id and x_supplier_id.strip() else None


def svc(request: Request) -> RfqService:
    return request.app.state.service


def reviews_svc(request: Request) -> ReviewService:
    return request.app.state.reviews


def deals_svc(request: Request) -> DealService:
    return request.app.state.deals


def internal_only(request: Request, x_internal_token: Annotated[str | None, Header()] = None) -> None:
    """Service-to-service guard (defence in depth: the app middleware also enforces the token)."""
    token = request.app.state.internal_token
    if token and not hmac.compare_digest((x_internal_token or "").encode(), token.encode()):
        raise Unauthenticated("Missing or invalid X-Internal-Token", code="invalid_internal_token")


def optional_user(x_user_id: Annotated[str | None, Header()] = None) -> str | None:
    return x_user_id.strip() if x_user_id and x_user_id.strip() else None


def display_name(x_user_name: Annotated[str | None, Header()] = None) -> str | None:
    """Gateway-set (percent-encoded) account name; used only to derive 'First L.'."""
    return unquote(x_user_name)[:100] if x_user_name else None


User = Annotated[str, Depends(current_user)]
Supplier = Annotated[str | None, Depends(verified_supplier)]
Svc = Annotated[RfqService, Depends(svc)]
Reviews = Annotated[ReviewService, Depends(reviews_svc)]
Deals = Annotated[DealService, Depends(deals_svc)]
MaybeUser = Annotated[str | None, Depends(optional_user)]
SupplierRef = Annotated[str, Path(min_length=1, max_length=64)]
Page = Annotated[int, Query(ge=1)]
Size = Annotated[int, Query(ge=1, le=100)]


@router.post("/requests", status_code=201)
async def create_request(body: RequestCreate, user: User, s: Svc) -> dict[str, Any]:
    return await s.create_request(user, body)


@router.get("/requests")
async def list_requests(
    user: User, s: Svc, scope: Annotated[str, Query(pattern="^(mine|public)$")] = "mine",
    status: RequestStatus | None = None, kind: ListingKind | None = None, page: Page = 1, page_size: Size = 20,
) -> dict[str, Any]:
    return await s.list_requests(user, scope=scope, status=status.value if status else None,
                                 kind=kind.value if kind else None, p=page, size=page_size)


@router.get("/requests/{request_id}")
async def get_request(request_id: str, user: User, s: Svc) -> dict[str, Any]:
    return await s.get_request(user, request_id)


@router.post("/requests/{request_id}/close")
async def close_request(request_id: str, user: User, s: Svc) -> dict[str, Any]:
    return await s.close_request(user, request_id)


@router.get("/requests/{request_id}/suggestions")
async def suggestions(request_id: str, user: User, s: Svc,
                      limit: Annotated[int, Query(ge=1, le=20)] = 5) -> dict[str, Any]:
    return await s.suggestions(user, request_id, limit)


@router.post("/requests/{request_id}/offers", status_code=201)
async def create_offer(request_id: str, body: OfferCreate, user: User, supplier: Supplier, s: Svc) -> dict[str, Any]:
    return await s.create_offer(user, request_id, body, supplier_id=supplier)


@router.get("/requests/{request_id}/offers")
async def list_offers(request_id: str, user: User, s: Svc, status: OfferStatus | None = None,
                      page: Page = 1, page_size: Size = 20) -> dict[str, Any]:
    return await s.list_offers(user, request_id, status.value if status else None, page, page_size)


@router.post("/offers/{offer_id}/accept")
async def accept_offer(offer_id: str, user: User, s: Svc) -> dict[str, Any]:
    return await s.accept_offer(user, offer_id)


@router.post("/offers/{offer_id}/reject")
async def reject_offer(offer_id: str, user: User, s: Svc) -> dict[str, Any]:
    return await s.reject_offer(user, offer_id)


@router.post("/offers/{offer_id}/withdraw")
async def withdraw_offer(offer_id: str, user: User, s: Svc) -> dict[str, Any]:
    return await s.withdraw_offer(user, offer_id)


@router.get("/deals")
async def list_deals(user: User, d: Deals, role: Annotated[str, Query(pattern="^(buyer|supplier|any)$")] = "any",
                     status: DealStatus | None = None, page: Page = 1, page_size: Size = 20) -> dict[str, Any]:
    return await d.list_for_user(user, role, status.value if status else None, page, page_size)


@router.get("/requests/{request_id}/deal")
async def request_deal(request_id: str, user: User, d: Deals) -> dict[str, Any]:
    return await d.for_request(user, request_id)


@router.get("/deals/{deal_id}")
async def get_deal(deal_id: str, user: User, s: Svc) -> dict[str, Any]:
    return await s.get_deal(user, deal_id)


@router.post("/deals/{deal_id}/fulfilment/start")
async def start_fulfilment(deal_id: str, user: User, supplier: Supplier, d: Deals) -> dict[str, Any]:
    return await d.start_fulfilment(user, supplier, deal_id)


@router.post("/deals/{deal_id}/delivered")
async def mark_delivered(deal_id: str, user: User, supplier: Supplier, d: Deals) -> dict[str, Any]:
    return await d.delivered(user, supplier, deal_id)


@router.post("/deals/{deal_id}/confirm-receipt")
async def confirm_receipt(deal_id: str, user: User, d: Deals) -> dict[str, Any]:
    return await d.confirm_receipt(user, deal_id)


@router.get("/deals/{deal_id}/events")
async def deal_events(deal_id: str, user: User, d: Deals) -> dict[str, Any]:
    return await d.events(user, deal_id)


@router.post("/internal/deals/{deal_id}/payment-status", dependencies=[Depends(internal_only)])
async def payment_status(deal_id: str, body: PaymentStatusCallback, d: Deals) -> dict[str, Any]:
    """payments -> rfq only. Never routed by the gateway."""
    return await d.apply_payment_status(deal_id, body)


# ---- verified-deal reviews --------------------------------------------------------------------
@router.post("/deals/{deal_id}/reviews", status_code=201)
async def create_review(deal_id: str, body: ReviewCreate, user: User, name: Annotated[str | None, Depends(display_name)],
                        r: Reviews) -> dict[str, Any]:
    return await r.create(user, deal_id, body, name)


@router.get("/suppliers/{supplier_ref}/reviews")
async def list_reviews(supplier_ref: SupplierRef, viewer: MaybeUser, r: Reviews,
                       sort: Annotated[str, Query(pattern="^(recent|rating)$")] = "recent",
                       page: Page = 1, page_size: Size = 20) -> dict[str, Any]:
    return await r.list_for_supplier(supplier_ref, sort=sort, p=page, size=page_size, viewer=viewer)


@router.get("/suppliers/{supplier_ref}/review-summary")
async def review_summary(supplier_ref: SupplierRef, r: Reviews) -> dict[str, Any]:
    return await r.summary(supplier_ref)


@router.put("/reviews/{review_id}")
async def update_review(review_id: str, body: ReviewCreate, user: User, r: Reviews) -> dict[str, Any]:
    return await r.update(user, review_id, body)


@router.delete("/reviews/{review_id}")
async def delete_review(review_id: str, user: User, r: Reviews) -> dict[str, Any]:
    return await r.delete(user, review_id)


@router.post("/reviews/{review_id}/reply", status_code=201)
async def reply_review(review_id: str, body: ReplyCreate, user: User, supplier: Supplier, r: Reviews) -> dict[str, Any]:
    return await r.reply(user, supplier, review_id, body)


@router.post("/reviews/{review_id}/report")
async def report_review(review_id: str, body: ReportCreate, user: User, r: Reviews) -> dict[str, Any]:
    return await r.report(user, review_id, body)
