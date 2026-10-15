from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel

from ..domain import pricehistory as ph
from ..domain import reco
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
ID = Annotated[str, Path(min_length=1, max_length=128)]


def svc(request: Request) -> SourcingService:
    return request.app.state.service


@router.get("/search", response_model=SearchResponse, response_model_exclude_none=True)
async def search(
    request: Request,
    q: str = Query("", max_length=200),
    kind: ListingKind | None = None,
    condition: Literal["new", "used", "refurbished", "any"] = "any",
    origin_country: str | None = Query(None, min_length=2, max_length=2, pattern="^[A-Za-z]{2}$"),
    category: str | None = Query(None, max_length=100),
    min_price: Decimal | None = Query(None, ge=0, max_digits=24, decimal_places=8),
    max_price: Decimal | None = Query(None, ge=0, max_digits=24, decimal_places=8),
    moq_max: int | None = Query(None, ge=0, le=2_000_000_000),
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
    res = await svc(request).search(query, page, page_size, sort)
    await request.app.state.analytics.impressions([i.id for i in res.items if i.source == "native"])
    return res


@router.get("/listings/{listing_id}", response_model=ListingDetail, response_model_exclude_none=True)
async def get_listing(listing_id: ID, request: Request) -> ListingDetail:
    item = await svc(request).get_listing(listing_id)
    if item is None:
        raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
    return item


@router.get("/suppliers/{supplier_id}", response_model=Supplier)
async def get_supplier(supplier_id: ID, request: Request) -> Supplier:
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


@router.get(
    "/listings/{listing_id}/price-history", response_model=ph.PriceHistory, response_model_exclude_none=True
)
async def price_history(
    listing_id: ID,
    request: Request,
    days: int = Query(90, ge=1, le=365),
    bucket: ph.Bucket = "day",
) -> ph.PriceHistory:
    service = svc(request)
    item = await service.get_listing(listing_id)  # also records today's observation for non-mock sources
    if item is None:
        raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
    now = datetime.now(UTC)
    if item.source == "mock":
        obs = ph.synthetic_observations(item.id, item.price.min.amount, item.price.min.currency, now, days)
    else:
        obs = await service.stored_prices(item.id, now - timedelta(days=days))
    return ph.build(
        item.id, obs, days, bucket, now, unit=item.unit, synthetic=item.source == "mock",
        currency=item.price.min.currency,
    )


class SimilarResponse(BaseModel):
    listing_id: str
    items: list[reco.Recommended]
    total: int
    warning: str | None = None  # additive: set when the time budget cut the work short (partial results)


class RecommendationsResponse(BaseModel):
    items: list[reco.Recommended]
    total: int
    based_on: list[str]  # the reference ids that resolved to listings (others are ignored)
    warning: str | None = None  # additive: set when the time budget cut the work short (partial results)


@router.get("/listings/{listing_id}/similar", response_model=SimilarResponse, response_model_exclude_none=True)
async def similar(listing_id: ID, request: Request, limit: int = Query(10, ge=1, le=30)) -> SimilarResponse:
    found = await svc(request).similar(listing_id, limit)
    if found is None:
        raise ApiError(404, "listing_not_found", f"Listing {listing_id} not found")
    return SimilarResponse(listing_id=listing_id, items=found[1], total=len(found[1]), warning=found[2])


_REF_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}\Z")
MAX_REFS = 20


@router.get("/recommendations", response_model=RecommendationsResponse, response_model_exclude_none=True)
async def recommendations(
    request: Request,
    ref: str = Query("", max_length=1500, description="Comma-separated recently viewed listing ids, most recent first"),
    country: str | None = Query(None, min_length=2, max_length=2, pattern="^[A-Za-z]{2}$"),
    limit: int = Query(20, ge=1, le=50),
) -> RecommendationsResponse:
    ids: list[str] = []
    for part in ref.split(","):
        part = part.strip()
        if not part:
            continue
        if not _REF_RE.match(part):
            raise ApiError(422, "invalid_ref", "ref must be comma-separated listing ids")
        if part not in ids:
            ids.append(part)
    if len(ids) > MAX_REFS:
        raise ApiError(422, "too_many_refs", f"At most {MAX_REFS} ref ids are allowed")
    based_on, items, warning = await svc(request).recommendations(ids, country, limit)
    return RecommendationsResponse(items=items, total=len(items), based_on=based_on, warning=warning)
