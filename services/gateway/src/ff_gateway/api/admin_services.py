"""Admin-only allow-listed passthroughs to trust (verification), freight and feed admin routes.

Same hardening as admin_moderation/admin_payments: X-Admin-Token == FF_GATEWAY_ADMIN_TOKEN (404 unset, 401 wrong), then
the gateway-side service admin token (FF_TRUST_ADMIN_TOKEN / FF_FREIGHT_ADMIN_TOKEN / FF_FEED_ADMIN_TOKEN; 404 when
unset) is injected together with the internal token and the fixed actor id. Only an explicit (method, path) allow-list
is reachable; path ids are validated, query params are allow-listed, client identity/admin headers are never forwarded.
"""

import re
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, Request, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_gateway.api.admin import require_admin, sanitize_reviewer
from ff_gateway.api.admin_demand import ADMIN_ACTOR, MAX_ADMIN_BODY, _seg
from ff_gateway.api.deps import internal_headers
from ff_gateway.domain.errors import PayloadTooLarge, UpstreamTimeout, UpstreamUnavailable

router = APIRouter(tags=["admin"])

_ID = r"[A-Za-z0-9_-]{1,64}"
_VALUE_RE = re.compile(r"^[A-Za-z0-9_=.:,+@-]{1,300}\Z")
_NUM_PARAMS = {"limit": 500, "offset": 1_000_000}


@dataclass(frozen=True)
class AdminService:
    name: str  # upstream key
    public_prefix: str  # gateway path prefix (client-facing)
    upstream_prefix: str  # path prefix at the service
    token_attr: str  # Settings attribute with the service admin token
    routes: tuple[tuple[str, str], ...]  # (method, regex of the path remainder after the prefix)
    query: frozenset[str]
    reviewer: bool = False  # add X-Reviewer: admin (trust audit log)


def _r(method: str, pattern: str) -> tuple[str, str]:
    return method, "^" + pattern.replace("{id}", _ID) + r"\Z"


SERVICES = (
    AdminService(
        "trust", "/v1/admin/trust/verification", "/v1/admin/trust/verification", "trust_admin_token",
        (
            _r("GET", "/documents"), _r("POST", "/documents/{id}/decision"),
            _r("PUT", "/documents/{id}/expiry"), _r("GET", "/audit"),
        ),
        frozenset({"status", "limit", "offset", "document_id", "supplier_id"}),
        reviewer=True,
    ),
    AdminService(
        "freight", "/v1/admin/freight", "/v1/admin/freight", "freight_admin_token",
        (
            _r("GET", "/applications"), _r("POST", "/applications/{id}/approve"), _r("POST", "/applications/{id}/reject"),
            _r("GET", "/forwarders"), _r("POST", "/forwarders/{id}/suspend"), _r("POST", "/forwarders/{id}/reinstate"),
            _r("GET", "/requests"), _r("POST", "/requests/{id}/hide"), _r("POST", "/requests/{id}/restore"),
            _r("GET", "/quotes"), _r("POST", "/quotes/{id}/hide"), _r("POST", "/quotes/{id}/restore"),
            _r("GET", "/reports"), _r("POST", "/sweep"),
        ),
        frozenset({"status", "visibility", "request_id", "target_type", "target_id", "cursor", "limit"}),
    ),
    AdminService(
        "feed", "/v1/admin/feed", "/v1/admin/feed", "feed_admin_token",
        (
            _r("GET", "/posts"), _r("POST", "/posts/{id}/hide"), _r("POST", "/posts/{id}/restore"),
            _r("GET", "/comments"), _r("POST", "/comments/{id}/hide"), _r("POST", "/comments/{id}/restore"),
            _r("GET", "/reports"),
        ),
        frozenset({"status", "post_id", "target_type", "target_id", "cursor", "limit"}),
    ),
)


def _bad(msg: str) -> StarletteHTTPException:
    return StarletteHTTPException(422, msg)


def _query(svc: AdminService, request: Request) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in request.query_params.multi_items():
        if k not in svc.query:
            raise _bad(f"Unsupported query parameter: {k}")
        if k in _NUM_PARAMS and not (v.isdigit() and int(v) <= _NUM_PARAMS[k] and (k == "offset" or int(v) > 0)):
            raise _bad(f"Invalid {k}")
        if not _VALUE_RE.match(v):
            raise _bad(f"Invalid {k}")
        out.append((k, v))
    return out


def _make(svc: AdminService):
    compiled = [(m, re.compile(p)) for m, p in svc.routes]

    async def handler(rest: str, request: Request) -> Response:
        require_admin(request)
        token = getattr(request.app.state.settings, svc.token_attr)
        if not token:
            raise StarletteHTTPException(404, "Not Found")
        segs = [_seg(p) for p in rest.split("/") if p]
        remainder = "/" + "/".join(segs)
        if not any(m == request.method and rx.match(remainder) for m, rx in compiled):
            raise StarletteHTTPException(404, "Not Found")
        params = _query(svc, request)
        body = await request.body()
        if len(body) > MAX_ADMIN_BODY:
            raise PayloadTooLarge()
        headers = {
            k: v for k, v in request.headers.items() if k.lower() in ("accept", "accept-language", "content-type")
        }
        headers.update(internal_headers(request, ADMIN_ACTOR))
        headers["X-Admin-Token"] = token
        if svc.reviewer:
            headers["X-Reviewer"] = sanitize_reviewer(request.headers.get("x-reviewer"))
        base = request.app.state.settings.upstream_map()[svc.name].rstrip("/")
        try:
            resp = await request.app.state.http.request(
                request.method, base + svc.upstream_prefix + remainder, params=params,
                content=body or None, headers=headers,
            )
        except httpx.TimeoutException as e:
            raise UpstreamTimeout(svc.name) from e
        except httpx.HTTPError as e:
            raise UpstreamUnavailable(svc.name) from e
        out = {k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "cache-control")}
        return Response(content=resp.content, status_code=resp.status_code, headers=out)

    return handler


for _svc in SERVICES:
    _h = _make(_svc)
    for _m in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        router.add_api_route(
            _svc.public_prefix + "/{rest:path}", _h, methods=[_m],
            operation_id=f"admin{_svc.name.title()}Passthrough{_m.title()}",
        )
