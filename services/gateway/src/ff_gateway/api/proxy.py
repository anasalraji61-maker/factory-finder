"""Catch-all reverse proxy by path prefix."""

import json
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Request, Response

from ff_gateway.api.deps import bearer_token, current_user_id, internal_headers, require_verified
from ff_gateway.db import User
from ff_gateway.domain.circuit_breaker import CircuitBreaker
from ff_gateway.domain.client_ip import client_ip
from ff_gateway.domain.errors import (
    AccountDisabled,
    InvalidPath,
    InvalidToken,
    PayloadTooLarge,
    SupplierClaimRequired,
    UpstreamCircuitOpen,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from ff_gateway.domain.routing import (
    is_internal_only,
    is_listing_events,
    is_public,
    is_trust_verification_write_path,
    matched_prefix,
    resolve_upstream,
)
from ff_gateway.domain.security import token_version_ok

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
    "referrer-policy",  # private media: no-referrer must reach the client
    "x-quota-remaining",  # assistant per-day quota
}
BREAKER_STATUSES = {502, 503, 504}  # upstream answers that count as a failed call (transport errors / timeouts always do)
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


async def _load_user(request: Request, user_id: str) -> User | None:
    """The caller's user row, loaded at most once per request (never cached across requests, so claim and
    verification state are always current)."""
    st = request.state
    if getattr(st, "_proxy_user_id", None) != user_id:
        async with request.app.state.sessionmaker() as s:
            st._proxy_user = await s.get(User, user_id)
        st._proxy_user_id = user_id
    return st._proxy_user  # type: ignore[no-any-return]


async def _ensure_active(request: Request, user_id: str) -> None:
    """Disabled/deleted users (and tokens older than the last password change / logout-all) lose access on proxied
    routes within a few seconds (short cache, fail closed)."""
    state = request.app.state
    cache: dict[str, tuple[float, bool, int]] = state.__dict__.setdefault("_active_cache", {})
    now = state.clock.monotonic()
    hit = cache.get(user_id)
    if hit is not None and hit[0] > now:
        active, version = hit[1], hit[2]
    else:
        u = await _load_user(request, user_id)
        active = bool(u is not None and u.is_active)
        if u is None:
            cache.pop(user_id, None)
            raise InvalidToken("Token refers to an unknown user")
        version = u.token_version or 0
        if len(cache) >= ACTIVE_CACHE_MAX:
            cache.clear()
        cache[user_id] = (now + ACTIVE_CACHE_SECONDS, active, version)
    if not active:
        raise AccountDisabled()
    if not token_version_ok(getattr(request.state, "token_tv", None), version):
        raise InvalidToken("Token has been revoked")


def _is_error_envelope(content: bytes) -> bool:
    try:
        data = json.loads(content)
    except ValueError:
        return False
    return isinstance(data, dict) and isinstance(data.get("error"), dict)


def _is_listing_report(path: str) -> bool:
    parts = path.rstrip("/").split("/")
    return len(parts) == 5 and parts[:3] == ["", "v1", "listings"] and parts[4] == "report"


def _is_trust_report(method: str, path: str) -> bool:
    parts = path.rstrip("/").split("/")
    return method.upper() == "POST" and len(parts) == 6 and parts[:4] == ["", "v1", "trust", "suppliers"] and parts[5] == "report"


_ENCODED_TRICKS = ("%2e", "%2f", "%5c")  # double-encoded dot / slash / backslash: decoded again by the upstream


def _suspicious_path(path: str) -> bool:
    """Dot segments, empty segments (``//``), backslashes and still-encoded dots/slashes. The policy checks above run on the
    decoded path, so anything an upstream or a fronting proxy could normalise differently is refused outright."""
    segs = path.split("/")[1:]
    if segs and segs[-1] == "":
        segs = segs[:-1]  # one trailing slash is fine
    low = path.lower()
    return any(s in ("", ".", "..") for s in segs) or "\\" in path or any(ord(ch) < 32 or ord(ch) == 127 for ch in path) or any(t in low for t in _ENCODED_TRICKS)


@router.api_route("/{full_path:path}", methods=METHODS, include_in_schema=False)
async def proxy(full_path: str, request: Request) -> Response:
    path = "/" + full_path
    if _suspicious_path(path):
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
        u = await _load_user(request, user_id)
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
    for k in [k for k in headers if k.lower() in ("x-client-ip", "x-account-age-seconds", "x-email-verified")]:
        del headers[k]  # never relay a client-supplied value
    if user_id and upstream == "trust" and _is_trust_report(request.method, path):
        u = await _load_user(request, user_id)
        if u is None:
            raise InvalidToken("Token refers to an unknown user")
        created = u.created_at if u.created_at.tzinfo else u.created_at.replace(tzinfo=UTC)
        headers["X-Account-Age-Seconds"] = str(max(0, int((datetime.now(UTC) - created).total_seconds())))  # created_at is wall-clock
        headers["X-Email-Verified"] = "1" if (u.email and u.email_verified) else "0"  # from our own user record
    if upstream == "assistant" or (upstream == "sourcing" and is_listing_events(request.method, path)):
        # sourcing: transient input for the daily-salted viewer hash (never stored); assistant: anonymous quota key
        peer = request.client.host if request.client else None
        headers["X-Client-Ip"] = client_ip(peer, request.headers.get("x-forwarded-for"), request.app.state.settings.trusted_proxy_networks())
    if (
        user_id
        and (upstream in ("messaging", "rfq", "feed") or trust_verification or (upstream == "sourcing" and (path.startswith("/v1/my") or _is_listing_report(path))))
    ):  # verified claim from our DB, never from the client
        row = await _load_user(request, user_id)  # same row the active check used on a cache miss: one query, not two
        if row and row.supplier_id and row.supplier_claim_status == "verified":
            headers["X-Supplier-Id"] = row.supplier_id
        if trust_verification and "X-Supplier-Id" not in headers:
            raise SupplierClaimRequired()
        if row and row.name and upstream == "rfq":  # reviewer display name (rfq shows first name + initial only)
            headers["X-User-Name"] = quote(row.name[:100], safe="")
    base = request.app.state.settings.upstream_map()[upstream].rstrip("/")
    breaker: CircuitBreaker = request.app.state.breakers.get(upstream)
    if (retry_after := breaker.before()) is not None:
        raise UpstreamCircuitOpen(upstream, retry_after)  # fast-fail: the service is not called
    try:
        resp = await request.app.state.http.request(
            request.method,
            base + path,
            params=request.query_params.multi_items(),
            content=body or None,
            headers=headers,
        )
    except httpx.TimeoutException as e:
        breaker.failure()
        raise UpstreamTimeout(upstream) from e
    except httpx.HTTPError as e:
        breaker.failure()
        raise UpstreamUnavailable(upstream) from e
    except BaseException:
        breaker.abort()  # cancelled (client went away): no verdict, free the half-open probe slot
        raise
    if resp.status_code in BREAKER_STATUSES:
        breaker.failure()
    else:
        breaker.success()
    out = {k: v for k, v in resp.headers.items() if k.lower() in FORWARD_RESPONSE_HEADERS}
    if resp.status_code >= 400 and not _is_error_envelope(resp.content):
        # a crashing upstream (framework debug page, stack trace, plain text) or a framework-default 4xx body such as
        # {"detail":"Not Found"} must not leak through the gateway: always the standard envelope
        if resp.status_code >= 500:
            code, msg = "upstream_error", "Upstream service error"
        else:
            code = {404: "not_found", 405: "method_not_allowed"}.get(resp.status_code, "upstream_error")
            msg = "Not found" if resp.status_code == 404 else "Upstream request rejected"
        return Response(
            json.dumps({"error": {"code": code, "message": msg, "details": {}}}),
            status_code=resp.status_code, media_type="application/json",
        )  # fmt: skip
    return Response(content=resp.content, status_code=resp.status_code, headers=out)
