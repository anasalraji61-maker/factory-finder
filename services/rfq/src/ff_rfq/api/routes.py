"""Thin FastAPI routers (all logic lives in RfqService)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request

from ff_rfq.domain.enums import ListingKind, OfferStatus, RequestStatus
from ff_rfq.domain.errors import Unauthenticated
from ff_rfq.schemas import OfferCreate, RequestCreate
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


User = Annotated[str, Depends(current_user)]
Supplier = Annotated[str | None, Depends(verified_supplier)]
Svc = Annotated[RfqService, Depends(svc)]
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


@router.get("/deals/{deal_id}")
async def get_deal(deal_id: str, user: User, s: Svc) -> dict[str, Any]:
    return await s.get_deal(user, deal_id)
