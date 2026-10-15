"""Admin-only read of private media files (verification documents).

GET /v1/admin/media/files/{id}[.ext] -> media's /v1/media/admin/files/{id}. Guarded like the other admin routes
(X-Admin-Token == FF_GATEWAY_ADMIN_TOKEN; 404 when unset, 401 wrong). The gateway injects media's service admin token
FF_MEDIA_ADMIN_TOKEN (gateway-side; 404 when not configured) plus the internal token and the fixed actor id. Client
identity/admin headers and query strings are never forwarded. The response is streamed back with
`Cache-Control: private, no-store` and nosniff; there is no listing endpoint.
"""

import re

import httpx
from fastapi import APIRouter, Request, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_gateway.api.admin import require_admin
from ff_gateway.api.admin_demand import ADMIN_ACTOR
from ff_gateway.api.deps import internal_headers
from ff_gateway.domain.errors import UpstreamTimeout, UpstreamUnavailable

router = APIRouter(tags=["admin"])

_NAME_RE = re.compile(r"^[a-f0-9]{32}(\.(jpg|png|webp))?\Z")
_PASS = ("content-type", "cache-control", "x-content-type-options", "content-security-policy", "content-disposition",
         "cross-origin-resource-policy", "referrer-policy", "pragma")  # fmt: skip


@router.get("/v1/admin/media/files/{name}", operation_id="adminMediaFileGet")
async def admin_media_file(name: str, request: Request) -> Response:
    require_admin(request)
    token = request.app.state.settings.media_admin_token
    if not token:
        raise StarletteHTTPException(404, "Not Found")
    if not _NAME_RE.fullmatch(name) or request.query_params:
        raise StarletteHTTPException(404, "Not Found")
    headers = internal_headers(request, ADMIN_ACTOR)
    headers["X-Admin-Token"] = token
    base = request.app.state.settings.upstream_map()["media"].rstrip("/")
    try:
        resp = await request.app.state.http.request("GET", f"{base}/v1/media/admin/files/{name}", headers=headers)
    except httpx.TimeoutException as e:
        raise UpstreamTimeout("media") from e
    except httpx.HTTPError as e:
        raise UpstreamUnavailable("media") from e
    out = {k.lower(): v for k, v in resp.headers.items() if k.lower() in _PASS}
    if resp.status_code == 200:
        out["cache-control"] = "private, no-store"
    return Response(content=resp.content, status_code=resp.status_code, headers=out)
