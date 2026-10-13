"""Catch-all reverse proxy by path prefix."""

import httpx
from fastapi import APIRouter, Request, Response

from ff_gateway.api.deps import bearer_token, current_user_id, internal_headers
from ff_gateway.domain.errors import (
    InvalidPath,
    PayloadTooLarge,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from ff_gateway.domain.routing import is_public, resolve_upstream

router = APIRouter()

FORWARD_REQUEST_HEADERS = {"accept", "accept-language", "content-type", "user-agent", "if-none-match", "if-modified-since"}
FORWARD_RESPONSE_HEADERS = {"content-type", "cache-control", "etag", "last-modified", "content-language", "location"}
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


@router.api_route("/{full_path:path}", methods=METHODS, include_in_schema=False)
async def proxy(full_path: str, request: Request) -> Response:
    path = "/" + full_path
    if ".." in path.split("/"):
        raise InvalidPath()
    upstream = resolve_upstream(path)
    if upstream is None:
        return Response(
            '{"error":{"code":"not_found","message":"Route not found","details":{}}}',
            status_code=404, media_type="application/json",
        )  # fmt: skip
    if request.method == "OPTIONS":
        return Response(status_code=204)
    user_id: str | None = None
    if is_public(request.method, path):
        if bearer_token(request):
            try:  # optional identity on public routes; a bad token just means anonymous
                user_id = current_user_id(request)
            except Exception:
                user_id = None
    else:
        user_id = current_user_id(request)

    body = await request.body()
    if len(body) > request.app.state.settings.max_body_bytes:
        raise PayloadTooLarge()
    headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARD_REQUEST_HEADERS}
    headers.update(internal_headers(request, user_id))
    base = request.app.state.settings.upstream_map()[upstream].rstrip("/")
    try:
        resp = await request.app.state.http.request(
            request.method, base + path, params=request.query_params.multi_items(), content=body or None, headers=headers
        )
    except httpx.TimeoutException as e:
        raise UpstreamTimeout(upstream) from e
    except httpx.HTTPError as e:
        raise UpstreamUnavailable(upstream) from e
    out = {k: v for k, v in resp.headers.items() if k.lower() in FORWARD_RESPONSE_HEADERS}
    return Response(content=resp.content, status_code=resp.status_code, headers=out)
