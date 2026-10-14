"""Admin-only proxy to sourcing moderation (/v1/admin/moderation/*).

Guarded like the other admin routes (X-Admin-Token; 404 when FF_GATEWAY_ADMIN_TOKEN is unset). Client identity and
admin headers are never forwarded: sourcing sees the fixed actor id plus the internal token and the service admin
token FF_SOURCING_ADMIN_TOKEN (gateway-side setting). 404 if that token is not configured.
"""

import httpx
from fastapi import APIRouter, Request, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_gateway.api.admin import require_admin
from ff_gateway.api.admin_demand import ADMIN_ACTOR, MAX_ADMIN_BODY, _seg
from ff_gateway.api.deps import internal_headers
from ff_gateway.domain.errors import PayloadTooLarge, UpstreamTimeout, UpstreamUnavailable

router = APIRouter(tags=["admin"])


async def moderation(rest: str, request: Request) -> Response:
    require_admin(request)
    token = request.app.state.settings.sourcing_admin_token
    if not token:
        raise StarletteHTTPException(404, "Not Found")
    segments = [_seg(p) for p in rest.split("/") if p]
    body = await request.body()
    if len(body) > MAX_ADMIN_BODY:
        raise PayloadTooLarge()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() in ("accept", "accept-language", "content-type")
    }
    headers.update(internal_headers(request, ADMIN_ACTOR))
    headers["X-Admin-Token"] = token
    base = request.app.state.settings.upstream_map()["sourcing"].rstrip("/")
    url = base + "/v1/admin/moderation" + ("/" + "/".join(segments) if segments else "")
    try:
        resp = await request.app.state.http.request(
            request.method,
            url,
            params=request.query_params.multi_items(),
            content=body or None,
            headers=headers,
        )
    except httpx.TimeoutException as e:
        raise UpstreamTimeout("sourcing") from e
    except httpx.HTTPError as e:
        raise UpstreamUnavailable("sourcing") from e
    out = {k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "cache-control")}
    return Response(content=resp.content, status_code=resp.status_code, headers=out)


for _m in ("GET", "POST", "PUT", "PATCH", "DELETE"):
    router.add_api_route(
        "/v1/admin/moderation/{rest:path}",
        moderation,
        methods=[_m],
        operation_id=f"adminModeration{_m.title()}",
    )
