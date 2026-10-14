"""Moderation endpoints: user reports (X-User-Id from the gateway) and admin tools (X-Admin-Token)."""

from __future__ import annotations

import hmac
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..domain.native import Line, Multi
from ..native_service import NativeService
from .errors import ApiError

router = APIRouter()
_USER_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")
_SUPPLIER_RE = re.compile(r"^sup_[A-Za-z0-9_.:\-]{1,59}$")

ReportReason = Literal[
    "prohibited_item", "counterfeit", "scam_or_fraud", "misleading", "contact_info_in_listing", "offensive", "other"
]


def native(request: Request) -> NativeService:
    return request.app.state.native


Svc = Annotated[NativeService, Depends(native)]


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: ReportReason
    details: Annotated[Multi, Field(max_length=500)] | None = None


class HideIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: Annotated[Line, Field(min_length=3, max_length=300)]


def reporter(x_user_id: Annotated[str | None, Header()] = None) -> str:
    v = (x_user_id or "").strip()
    if not _USER_RE.match(v):
        raise ApiError(401, "auth_required", "A signed-in user is required to report a listing")
    return v


def require_admin(request: Request, x_admin_token: Annotated[str | None, Header()] = None) -> None:
    secret = request.app.state.admin_token
    if not secret:  # admin tools are disabled unless a token is configured
        raise StarletteHTTPException(404, "Not Found")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), secret.encode()):
        raise ApiError(401, "admin_auth_required", "Valid X-Admin-Token required")


@router.post("/v1/listings/{listing_id}/report")
async def report_listing(
    listing_id: str,
    body: ReportIn,
    s: Svc,
    response: Response,
    user: Annotated[str, Depends(reporter)],
    x_supplier_id: Annotated[str | None, Header()] = None,
) -> dict:
    own = x_supplier_id.strip() if x_supplier_id and _SUPPLIER_RE.match(x_supplier_id.strip()) else None
    await s.report(user, listing_id, body.reason, body.details, own)
    response.status_code = 202  # identical for first and repeated reports: nothing about prior state leaks
    return {"status": "received"}


admin = APIRouter(prefix="/v1/admin/moderation", dependencies=[Depends(require_admin)])
Page = Annotated[int, Query(ge=1)]
Size = Annotated[int, Query(ge=1, le=100)]


@admin.get("/reports")
async def list_reports(
    s: Svc,
    status: Literal["open", "actioned", "dismissed", "all"] = "open",
    listing_id: Annotated[str | None, Query(max_length=16)] = None,
    page: Page = 1,
    page_size: Size = 20,
) -> dict:
    return await s.admin_reports(None if status == "all" else status, listing_id, page, page_size)


@admin.get("/listings")
async def list_moderated(
    s: Svc,
    status: Literal["pending_review", "hidden", "all"] = "all",
    page: Page = 1,
    page_size: Size = 20,
) -> dict:
    return await s.admin_listings(None if status == "all" else status, page, page_size)


@admin.post("/listings/{listing_id}/hide")
async def hide_listing(listing_id: str, body: HideIn, s: Svc) -> dict:
    return await s.admin_moderate(listing_id, "hide", body.reason)


@admin.post("/listings/{listing_id}/restore")
async def restore_listing(listing_id: str, s: Svc) -> dict:
    return await s.admin_moderate(listing_id, "restore")
