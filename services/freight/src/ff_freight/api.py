"""Thin routers. User routes under /v1/freight, forwarder approval + moderation under /v1/admin/freight."""

from __future__ import annotations

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Request

from ff_freight import privacy
from ff_freight.errors import NotFound, Unauthenticated
from ff_freight.schemas import (
    ID_RE,
    USER_RE,
    AcceptIn,
    ApplicationCreate,
    NoteIn,
    ProfileUpdate,
    QuoteCreate,
    RatingIn,
    ReasonIn,
    ReportIn,
    RequestCreate,
)
from ff_freight.service import FreightService

router = APIRouter(prefix="/v1/freight")
admin = APIRouter(prefix="/v1/admin/freight")
internal = APIRouter(prefix="/v1/internal")


def svc(request: Request) -> FreightService:
    return request.app.state.service


def current_user(request: Request, x_user_id: Annotated[str | None, Header()] = None) -> str:
    """Gateway-derived identity. Forwarder status is resolved from this service's own approved
    forwarders table, never from a client-supplied header or body (see docs/decisions/freight.md)."""
    v = (x_user_id or "").strip()
    if not v:
        raise Unauthenticated("X-User-Id header is required")
    if not USER_RE.match(v):
        raise Unauthenticated("Invalid X-User-Id")
    request.state.user_id = v
    return v


def require_admin(request: Request, x_admin_token: Annotated[str | None, Header()] = None) -> None:
    secret = request.app.state.settings.admin_token_value
    if not secret:  # admin endpoints are disabled unless a token is configured
        raise NotFound("Not Found")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), secret.encode()):
        raise Unauthenticated("Valid X-Admin-Token required", code="admin_auth_required")


def privacy_guard(request: Request, x_internal_token: Annotated[str | None, Header()] = None) -> None:
    """Export/erasure: internal token only; anything else looks like a missing route."""
    token = request.app.state.settings.internal_token_value
    if token is not None and not hmac.compare_digest((x_internal_token or "").encode(), token.encode()):
        raise NotFound("Not Found")


S = Annotated[FreightService, Depends(svc)]
User = Annotated[str, Depends(current_user)]
Cursor = Annotated[str | None, Query(max_length=300)]
Limit = Annotated[int | None, Query(ge=1, le=50)]
ObjId = Annotated[str, Path(pattern=ID_RE.pattern, max_length=40)]
Country = Annotated[str | None, Query(pattern=r"^[A-Z]{2}$")]
ReqStatus = Annotated[str | None, Query(pattern="^(open|awarded|closed|expired)$")]
AdminStatus = Annotated[str, Query(pattern="^(pending|approved|rejected|all)$")]
FwdStatus = Annotated[str, Query(pattern="^(active|suspended|all)$")]
Visibility = Annotated[str, Query(pattern="^(visible|hidden|all)$")]
AnyReqStatus = Annotated[str, Query(pattern="^(open|awarded|closed|expired|all)$")]
Sort = Annotated[Literal["score", "price", "transit", "rating"], Query()]


# ---- identity / applications
@router.get("/me")
async def me(s: S, user: User):
    return await s.whoami(user)


@router.post("/applications", status_code=201)
async def apply(body: ApplicationCreate, s: S, user: User):
    return await s.apply(user, body)


@router.get("/applications/mine")
async def my_applications(s: S, user: User):
    return await s.my_applications(user)


# ---- forwarders ("me" routes are declared before the {forwarder_id} routes)
@router.get("/forwarders/me")
async def my_profile(s: S, user: User):
    return await s.my_profile(user)


@router.patch("/forwarders/me")
async def update_profile(body: ProfileUpdate, s: S, user: User):
    return await s.update_profile(user, body)


@router.get("/forwarders/me/inbox")
async def inbox(s: S, user: User, cursor: Cursor = None, limit: Limit = None):
    return await s.inbox(user, cursor, limit)


@router.get("/forwarders/me/quotes")
async def my_quotes(
    s: S, user: User,
    status: Annotated[str | None, Query(pattern="^(submitted|accepted|rejected|withdrawn)$")] = None,
    cursor: Cursor = None, limit: Limit = None,
):  # fmt: skip
    return await s.my_quotes(user, status, cursor, limit)


@router.get("/forwarders")
async def list_forwarders(
    s: S, user: User, origin_country: Country = None, destination_country: Country = None,
    mode: Annotated[Literal["sea", "air", "road", "rail"] | None, Query()] = None,
    incoterm: Annotated[str | None, Query(pattern="^(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)$")] = None,
    cursor: Cursor = None, limit: Limit = None,
):  # fmt: skip
    return await s.list_forwarders(origin_country, destination_country, mode, incoterm, cursor, limit)


@router.get("/forwarders/{forwarder_id}")
async def get_forwarder(forwarder_id: ObjId, s: S, user: User):
    return await s.get_forwarder(user, forwarder_id)


@router.get("/forwarders/{forwarder_id}/ratings")
async def forwarder_ratings(forwarder_id: ObjId, s: S, user: User, cursor: Cursor = None, limit: Limit = None):
    return await s.forwarder_ratings(forwarder_id, cursor, limit)


# ---- shipment requests
@router.post("/requests", status_code=201)
async def create_request(body: RequestCreate, s: S, user: User):
    return await s.create_request(user, body)


@router.get("/requests")
async def list_requests(s: S, user: User, status: ReqStatus = None, cursor: Cursor = None, limit: Limit = None):
    return await s.list_requests(user, status, cursor, limit)


@router.get("/requests/{request_id}")
async def get_request(request_id: ObjId, s: S, user: User):
    return await s.get_request(user, request_id)


@router.post("/requests/{request_id}/close")
async def close_request(request_id: ObjId, s: S, user: User):
    return await s.close_request(user, request_id)


@router.post("/requests/{request_id}/quotes", status_code=201)
async def submit_quote(request_id: ObjId, body: QuoteCreate, s: S, user: User):
    return await s.submit_quote(user, request_id, body)


@router.get("/requests/{request_id}/quotes")
async def list_quotes(
    request_id: ObjId, s: S, user: User,
    status: Annotated[str | None, Query(pattern="^(submitted|accepted|rejected|withdrawn)$")] = None,
    cursor: Cursor = None, limit: Limit = None,
):  # fmt: skip
    return await s.list_quotes(user, request_id, status, cursor, limit)


@router.get("/requests/{request_id}/comparison")
async def comparison(request_id: ObjId, s: S, user: User, sort: Sort = "score"):
    return await s.comparison(user, request_id, sort)


@router.post("/requests/{request_id}/rating", status_code=201)
async def rate(request_id: ObjId, body: RatingIn, s: S, user: User):
    return await s.rate(user, request_id, body)


@router.post("/requests/{request_id}/report", status_code=202)
async def report_request(request_id: ObjId, body: ReportIn, s: S, user: User):
    return await s.report(user, "request", request_id, body.reason, body.details)


# ---- quotes
@router.get("/quotes/{quote_id}")
async def get_quote(quote_id: ObjId, s: S, user: User):
    return await s.get_quote(user, quote_id)


@router.put("/quotes/{quote_id}")
async def revise_quote(quote_id: ObjId, body: QuoteCreate, s: S, user: User):
    return await s.revise_quote(user, quote_id, body)


@router.post("/quotes/{quote_id}/withdraw")
async def withdraw_quote(quote_id: ObjId, s: S, user: User):
    return await s.withdraw_quote(user, quote_id)


@router.post("/quotes/{quote_id}/accept")
async def accept_quote(quote_id: ObjId, s: S, user: User, body: AcceptIn | None = None):
    return await s.accept_quote(user, quote_id, body.revision if body else None)


@router.post("/quotes/{quote_id}/report", status_code=202)
async def report_quote(quote_id: ObjId, body: ReportIn, s: S, user: User):
    return await s.report(user, "quote", quote_id, body.reason, body.details)


@router.post("/forwarders/{forwarder_id}/report", status_code=202)
async def report_forwarder(forwarder_id: ObjId, body: ReportIn, s: S, user: User):
    return await s.report(user, "forwarder", forwarder_id, body.reason, body.details)


# ---- admin (X-Admin-Token; 404 when FF_FREIGHT_ADMIN_TOKEN is unset)
dep = [Depends(require_admin)]


@admin.get("/applications", dependencies=dep)
async def admin_applications(s: S, status: AdminStatus = "pending", cursor: Cursor = None, limit: Limit = None):
    return await s.admin_applications(status, cursor, limit)


@admin.post("/applications/{application_id}/approve", dependencies=dep)
async def admin_approve(application_id: ObjId, s: S, body: NoteIn | None = None):
    return await s.admin_approve(application_id, body.note if body else None)


@admin.post("/applications/{application_id}/reject", dependencies=dep)
async def admin_reject(application_id: ObjId, body: ReasonIn, s: S):
    return await s.admin_reject(application_id, body.reason)


@admin.get("/forwarders", dependencies=dep)
async def admin_forwarders(s: S, status: FwdStatus = "all", cursor: Cursor = None, limit: Limit = None):
    return await s.admin_forwarders(status, cursor, limit)


@admin.post("/forwarders/{forwarder_id}/suspend", dependencies=dep)
async def admin_suspend(forwarder_id: ObjId, body: ReasonIn, s: S):
    return await s.admin_set_forwarder(forwarder_id, True, body.reason)


@admin.post("/forwarders/{forwarder_id}/reinstate", dependencies=dep)
async def admin_reinstate(forwarder_id: ObjId, s: S):
    return await s.admin_set_forwarder(forwarder_id, False, None)


@admin.get("/requests", dependencies=dep)
async def admin_requests(
    s: S, status: AnyReqStatus = "all", visibility: Visibility = "all", cursor: Cursor = None, limit: Limit = None
):
    return await s.admin_requests(status, visibility, cursor, limit)


@admin.post("/requests/{request_id}/hide", dependencies=dep)
async def admin_hide_request(request_id: ObjId, body: ReasonIn, s: S):
    return await s.admin_set_request(request_id, True, body.reason)


@admin.post("/requests/{request_id}/restore", dependencies=dep)
async def admin_restore_request(request_id: ObjId, s: S):
    return await s.admin_set_request(request_id, False, None)


@admin.get("/quotes", dependencies=dep)
async def admin_quotes(
    s: S, request_id: Annotated[str | None, Query(pattern=ID_RE.pattern)] = None,
    visibility: Visibility = "all", cursor: Cursor = None, limit: Limit = None,
):  # fmt: skip
    return await s.admin_quotes(request_id, visibility, cursor, limit)


@admin.post("/quotes/{quote_id}/hide", dependencies=dep)
async def admin_hide_quote(quote_id: ObjId, body: ReasonIn, s: S):
    return await s.admin_set_quote(quote_id, True, body.reason)


@admin.post("/quotes/{quote_id}/restore", dependencies=dep)
async def admin_restore_quote(quote_id: ObjId, s: S):
    return await s.admin_set_quote(quote_id, False, None)


@admin.get("/reports", dependencies=dep)
async def admin_reports(
    s: S, target_type: Annotated[str | None, Query(pattern="^(request|quote|forwarder)$")] = None,
    target_id: Annotated[str | None, Query(pattern=ID_RE.pattern)] = None,
    cursor: Cursor = None, limit: Limit = None,
):  # fmt: skip
    return await s.admin_reports(target_type, target_id, cursor, limit)


@admin.post("/sweep", dependencies=dep)
async def admin_sweep(s: S):
    return await s.admin_sweep()


@internal.post("/users/{user_id}/export", dependencies=[Depends(privacy_guard)])
async def export_user(user_id: str, s: S) -> dict:
    return {"service": "freight", "user_id": user_id, **await privacy.export_user(s.engine, user_id)}


@internal.delete("/users/{user_id}/data", dependencies=[Depends(privacy_guard)])
async def erase_user(user_id: str, s: S) -> dict:
    return {"service": "freight", "user_id": user_id, "status": "done", "counts": await privacy.erase_user(s.engine, user_id)}
