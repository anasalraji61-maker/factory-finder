from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query, Request

from ..domain.categories import CATEGORY_TREE
from ..domain.models import (
    CategoryNode,
    ListingDetail,
    ListingKind,
    SearchQuery,
    SearchResponse,
    Supplier,
)
from ..service import SourcingService
from .errors import ApiError

router = APIRouter(prefix="/v1")


def svc(request: Request) -> SourcingService:
    return request.app.state.service


@router.get("/search", response_model=SearchResponse)
async def search(
    request: Request,
    q: str = Query("", max_length=200),
    kind: ListingKind | None = None,
    condition: Literal["new", "used", "refurbished", "any"] = "any",
    origin_country: str | None = Query(None, min_length=2, max_length=2),
    category: str | None = None,
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    moq_max: int | None = Query(None, ge=0),
    verified_only: bool = False,
    sort: Literal["relevance", "price_asc", "price_desc", "trust", "moq"] = "relevance",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> SearchResponse:
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ApiError(422, "invalid_price_range", "min_price must be <= max_price")
    query = SearchQuery(
        q=q,
        kind=kind,
        condition=condition,
        origin_country=origin_country,
        category=category,
        min_price=min_price,
        max_price=max_price,
        moq_max=moq_max,
        verified_only=verified_only,
    )
    return await svc(request).search(query, page, page_size, sort)


@router.get("/listings/{listing_id}", response_model=ListingDetail)
async def get_listing(listing_id: str, request: Request) -> ListingDetail:
    item = await svc(request).get_listing(listing_id)
    if item is None:
        raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
    return item


@router.get("/suppliers/{supplier_id}", response_model=Supplier)
async def get_supplier(supplier_id: str, request: Request) -> Supplier:
    sup = await svc(request).get_supplier(supplier_id)
    if sup is None:
        raise ApiError(404, "supplier_not_found", f"Supplier {supplier_id} not found")
    return sup


@router.get("/categories", response_model=list[CategoryNode])
async def categories() -> list[CategoryNode]:
    return CATEGORY_TREE


@router.get("/sources")
async def sources(request: Request) -> list[dict]:
    return await svc(request).sources_overview()
