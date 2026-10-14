"""Catch-all reverse proxy by path prefix."""

from urllib.parse import quote

import httpx
from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from ff_gateway.api.deps import bearer_token, current_user_id, internal_headers, require_verified
from ff_gateway.db import User
from ff_gateway.domain.errors import (
    AccountDisabled,
    InvalidPath,
    InvalidToken,
    PayloadTooLarge,
    SupplierClaimRequired,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from ff_gateway.domain.routing import (
    is_internal_only,
    is_public,
    is_trust_verification_write_path,
    matched_prefix,
    resolve_upstream,
)

router = APIRouter()

FORWARD_REQUEST_HEADERS = {
    "accept",
    "accept-language",
    "content-type",
    "user-agent",
    "if-none-match",
    "if-modified-since",
}
FORWARD_RESPONSE_HEADERS = {
    "content-type",
    "cache-control",
    "etag",
    "last-modified",
    "content-language",
    "location",
    "x-content-type-options",  # media files: nosniff must reach the client
    "content-security-policy",
    "content-disposition",
    "cross-origin-resource-policy",
    "retry-after",
    "x-quota-remaining",  # assistant per-day quota
}
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _needs_verified(method: str, upstream: str, path: str) -> bool:
    """Sensitive writes: anything that moves money (payments) or publishes supplier listings/posts."""
    if method.upper() in ("GET", "HEAD", "OPTIONS"):
        return False
    return (
        upstream == "payments"
        or (upstream == "sourcing" and path.startswith("/v1/my"))
        or (upstream == "trust" and is_trust_verification_write_path(path))  # supplier verification documents
        or (upstream == "feed" and path.rstrip("/") == "/v1/feed/posts")  # publishing a supplier post
        or (upstream == "freight" and path.rstrip("/") in ("/v1/freight/applications", "/v1/freight/requests"))
    )


TRUST_VERIFICATION_MAX_BODY = 64 * 1024  # JSON metadata only; files go to media first
ACTIVE_CACHE_SECONDS = 5.0
ACTIVE_CACHE_MAX = 10_000


async def _ensure_active(request: Request, user_id: str) -> None:
    """Disabled/deleted users lose access on proxied routes within a few seconds (short cache, fail closed)."""
    state = request.app.state
    cache: dict[str, tuple[float, bool]] = state.__dict__.setdefault("_active_cache", {})
    now = state.clock.monotonic()
    hit = cache.get(user_id)
    if hit is not None and hit[0] > now:
        active = hit[1]
    else:
        async with state.sessionmaker() as s:
            u = await s.get(User, user_id)
        active = bool(u is not None and u.is_active)
        if u is None:
            cache.pop(user_id, None)
            raise InvalidToken("Token refers to an unknown user")
        if len(cache) >= ACTIVE_CACHE_MAX:
            cache.clear()
        cache[user_id] = (now + ACTIVE_CACHE_SECONDS, active)
    if not active:
        raise AccountDisabled()


def _is_listing_report(path: str) -> bool:
    parts = path.rstrip("/").split("/")
    return len(parts) == 5 and parts[:3] == ["", "v1", "listings"] and parts[4] == "report"


@router.api_route("/{full_path:path}", methods=METHODS, include_in_schema=False)
async def proxy(full_path: str, request: Request) -> Response:
    path = "/" + full_path
    if ".." in path.split("/") or "." in path.split("/"):
        # "." too: httpx collapses dot segments upstream, which would sidestep the exact-path internal-only /
        # verified-email / supplier-claim checks done on the pre-normalised path
        raise InvalidPath()
    upstream = resolve_upstream(path)
    if upstream is None:
        return Response(
            '{"error":{"code":"not_found","message":"Route not found","details":{}}}',
            status_code=404, media_type="application/json",
        )  # fmt: skip
    request.state.path_template = matched_prefix(path) + "/*"  # type: ignore[operator]
    if request.method == "OPTIONS":
        return Response(status_code=204)
    if is_internal_only(request.method, path):
        return Response(
            '{"error":{"code":"not_found","message":"Route not found","details":{}}}',
            status_code=404, media_type="application/json",
        )  # fmt: skip
    user_id: str | None = None
    if is_public(request.method, path):
        if bearer_token(request):
            try:  # optional identity on public routes; a bad token just means anonymous
                user_id = current_user_id(request)
            except Exception:
                user_id = None
    else:
        user_id = current_user_id(request)

    if user_id and request.app.state.settings.require_email_verified and _needs_verified(request.method, upstream, path):
        async with request.app.state.sessionmaker() as s:
            u = await s.get(User, user_id)
        if u is None:  # fail closed: a token for a deleted account must not reach money/listing writes
            raise InvalidToken("Token refers to an unknown user")
        if not u.is_active:
            raise AccountDisabled()
        require_verified(request, u)

    if user_id:
        await _ensure_active(request, user_id)

    body = await request.body()
    if len(body) > request.app.state.settings.max_body_bytes:
        raise PayloadTooLarge()
    trust_verification = upstream == "trust" and is_trust_verification_write_path(path)
    if trust_verification and len(body) > TRUST_VERIFICATION_MAX_BODY:
        raise PayloadTooLarge()
    headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARD_REQUEST_HEADERS}
    headers.update(internal_headers(request, user_id))
    if (
        user_id
        and (upstream in ("messaging", "rfq", "feed") or trust_verification or (upstream == "sourcing" and (path.startswith("/v1/my") or _is_listing_report(path))))
    ):  # verified claim from our DB, never from the client
        async with request.app.state.sessionmaker() as s:
            row = (
                await s.execute(
                    select(User.supplier_id, User.supplier_claim_status, User.name).where(User.id == user_id)
                )
            ).first()
        if row and row.supplier_id and row.supplier_claim_status == "verified":
            headers["X-Supplier-Id"] = row.supplier_id
        if trust_verification and "X-Supplier-Id" not in headers:
            raise SupplierClaimRequired()
        if row and row.name and upstream == "rfq":  # reviewer display name (rfq shows first name + initial only)
            headers["X-User-Name"] = quote(row.name[:100], safe="")
    base = request.app.state.settings.upstream_map()[upstream].rstrip("/")
    try:
        resp = await request.app.state.http.request(
            request.method,
            base + path,
            params=request.query_params.multi_items(),
            content=body or None,
            headers=headers,
        )
    except httpx.TimeoutException as e:
        raise UpstreamTimeout(upstream) from e
    except httpx.HTTPError as e:
        raise UpstreamUnavailable(upstream) from e
    out = {k: v for k, v in resp.headers.items() if k.lower() in FORWARD_RESPONSE_HEADERS}
    return Response(content=resp.content, status_code=resp.status_code, headers=out)
