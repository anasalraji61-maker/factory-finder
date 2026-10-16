"""Admin-only proxy to the demand service (X-Admin-Token guarded; 404 when FF_GATEWAY_ADMIN_TOKEN is unset).

Only an explicit allow-list of demand endpoints is reachable. Client identity headers are never
forwarded: upstream always sees the fixed actor id ADMIN_ACTOR plus the internal token.
"""

import httpx
from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select

from ff_gateway.api.admin import require_admin
from ff_gateway.api.deps import internal_headers
from ff_gateway.db import User
from ff_gateway.domain.errors import PayloadTooLarge, UpstreamTimeout, UpstreamUnavailable

router = APIRouter(tags=["admin"])
ADMIN_ACTOR = "admin"
MAX_ADMIN_BODY = 256 * 1024


async def _forward(request: Request, method: str, upstream_path: str) -> Response:
    require_admin(request)
    body = await request.body()
    if len(body) > MAX_ADMIN_BODY:
        raise PayloadTooLarge()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() in ("accept", "accept-language", "content-type")
    }
    headers.update(internal_headers(request, ADMIN_ACTOR))
    base = request.app.state.settings.upstream_map()["demand"].rstrip("/")
    try:
        resp = await request.app.state.http.request(
            method,
            base + upstream_path,
            params=request.query_params.multi_items(),
            content=body or None,
            headers=headers,
        )
    except httpx.TimeoutException as e:
        raise UpstreamTimeout("demand") from e
    except httpx.HTTPError as e:
        raise UpstreamUnavailable("demand") from e
    out = {k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "cache-control")}
    return Response(content=resp.content, status_code=resp.status_code, headers=out)


@router.get("/v1/admin/demand/signals")
async def list_signals(request: Request) -> Response:
    return await _forward(request, "GET", "/v1/signals")


@router.post("/v1/admin/demand/signals")
async def import_signal(request: Request) -> Response:
    return await _forward(request, "POST", "/v1/signals")


@router.post("/v1/admin/demand/signals/poll")
async def poll_signals(request: Request) -> Response:
    return await _forward(request, "POST", "/v1/signals/poll")


@router.get("/v1/admin/demand/signals/{signal_id}")
async def get_signal(signal_id: str, request: Request) -> Response:
    return await _forward(request, "GET", f"/v1/signals/{_seg(signal_id)}")


@router.get("/v1/admin/demand/drafts")
async def list_drafts(request: Request) -> Response:
    return await _forward(request, "GET", "/v1/drafts")


@router.get("/v1/admin/demand/drafts/{draft_id}")
async def get_draft(draft_id: str, request: Request) -> Response:
    return await _forward(request, "GET", f"/v1/drafts/{_seg(draft_id)}")


def _draft_post(action: str):
    async def handler(draft_id: str, request: Request) -> Response:
        return await _forward(request, "POST", f"/v1/drafts/{_seg(draft_id)}/{action}")

    handler.__name__ = "draft_" + action.replace("-", "_")
    return handler


for _a in ("approve", "reject", "mark-published", "outcome"):
    router.post(f"/v1/admin/demand/drafts/{{draft_id}}/{_a}")(_draft_post(_a))


@router.get("/v1/admin/demand/quota")
async def quota(request: Request) -> Response:
    return await _forward(request, "GET", "/v1/quota")


def _seg(value: str) -> str:
    """Path params are single segments already; refuse anything that could alter the upstream path."""
    from starlette.exceptions import HTTPException

    if not value or value in (".", "..") or "/" in value or "\\" in value or "%" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise HTTPException(404, "Not Found")
    return value


@router.get("/v1/admin/overview")
async def overview(request: Request) -> dict:
    require_admin(request)
    async with request.app.state.sessionmaker() as s:
        users = await s.scalar(select(func.count()).select_from(User))
        pending = await s.scalar(
            select(func.count())
            .select_from(User)
            .where(User.supplier_claim_status == "pending", User.supplier_id.is_not(None))
        )
    pending_drafts: int | None = None
    try:  # demand is optional: a failing upstream just yields null
        base = request.app.state.settings.upstream_map()["demand"].rstrip("/")
        r = await request.app.state.http.get(
            base + "/v1/drafts",
            params={"status": "draft"},
            headers=internal_headers(request, ADMIN_ACTOR),
        )
        if r.status_code == 200:
            pending_drafts = int(r.json().get("total", len(r.json().get("items", []))))
    except (httpx.HTTPError, ValueError, AttributeError, TypeError):
        pending_drafts = None
    return {"pending_supplier_claims": pending, "pending_drafts": pending_drafts, "users": users}
