"""Supplier-owned listings (/v1/my/listings). Identity = gateway-verified X-Supplier-Id only."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from ..adapters.native import OwnedListing
from ..domain.native import ListingWrite
from ..native_service import NativeService
from .errors import ApiError

router = APIRouter(prefix="/v1/my")
_SUPPLIER_RE = re.compile(r"^sup_[A-Za-z0-9_.:\-]{1,59}$")


def native(request: Request) -> NativeService:
    return request.app.state.native


def supplier_id(x_supplier_id: Annotated[str | None, Header()] = None) -> str:
    v = (x_supplier_id or "").strip()
    if not _SUPPLIER_RE.match(v):
        raise ApiError(403, "supplier_required", "A verified supplier account is required")
    return v


Supplier = Annotated[str, Depends(supplier_id)]
Svc = Annotated[NativeService, Depends(native)]
Status = Literal["draft", "published", "archived", "pending_review", "hidden"]


@router.post(
    "/listings", status_code=201, response_model=OwnedListing, response_model_exclude_none=True
)
async def create_listing(body: ListingWrite, sup: Supplier, s: Svc) -> OwnedListing:
    return await s.create(sup, body)


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[Any]
    dry_run: bool = False


@router.post("/listings/import")
async def import_listings(body: ImportBody, sup: Supplier, s: Svc) -> dict:
    return await s.import_listings(sup, body.items, body.dry_run)


@router.get("/listings")
async def list_listings(
    sup: Supplier,
    s: Svc,
    status: Status | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    out = await s.list(sup, status, page, page_size)
    out["items"] = [i.model_dump(mode="json", exclude_none=True) for i in out["items"]]
    return out


@router.get("/listings/{listing_id}", response_model=OwnedListing, response_model_exclude_none=True)
async def get_listing(listing_id: str, sup: Supplier, s: Svc) -> OwnedListing:
    return await s.get(sup, listing_id)


@router.put("/listings/{listing_id}", response_model=OwnedListing, response_model_exclude_none=True)
async def replace_listing(
    listing_id: str, body: ListingWrite, sup: Supplier, s: Svc
) -> OwnedListing:
    return await s.update(sup, listing_id, body)


@router.delete("/listings/{listing_id}", status_code=204)
async def delete_listing(listing_id: str, sup: Supplier, s: Svc) -> Response:
    await s.delete(sup, listing_id)
    return Response(status_code=204)


@router.post(
    "/listings/{listing_id}/publish", response_model=OwnedListing, response_model_exclude_none=True
)
async def publish_listing(listing_id: str, sup: Supplier, s: Svc) -> OwnedListing:
    return await s.publish(sup, listing_id)


@router.post(
    "/listings/{listing_id}/unpublish",
    response_model=OwnedListing,
    response_model_exclude_none=True,
)
async def unpublish_listing(listing_id: str, sup: Supplier, s: Svc) -> OwnedListing:
    return await s.unpublish(sup, listing_id)
