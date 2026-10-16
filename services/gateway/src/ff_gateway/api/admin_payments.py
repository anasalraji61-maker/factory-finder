"""Admin-only passthrough to the payments outbox (dead-letter view and requeue).

Allow-list: GET /v1/admin/payments/outbox and POST /v1/admin/payments/outbox/{id}/requeue. Guarded like the other
admin routes (X-Admin-Token == FF_GATEWAY_ADMIN_TOKEN; 404 when unset, 401 wrong). The gateway injects payments'
service admin token FF_PAYMENTS_ADMIN_TOKEN (gateway-side; 404 when not configured) plus the internal token and the
fixed actor id. Client identity/admin headers and bodies are never forwarded; only status/limit/cursor (and the
upstream's own page/page_size) query params pass.
"""

import json
import logging
import re

import httpx
from fastapi import APIRouter, Request, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_gateway.api.admin import require_admin, sanitize_reviewer
from ff_gateway.api.admin_demand import ADMIN_ACTOR, _seg
from ff_gateway.api.deps import internal_headers
from ff_gateway.domain.errors import UpstreamTimeout, UpstreamUnavailable

router = APIRouter(tags=["admin"])
log = logging.getLogger("ff_gateway.admin")

_ALLOWED_QUERY = {"status", "limit", "cursor", "page", "page_size"}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
_CURSOR_RE = re.compile(r"^[A-Za-z0-9_=.-]{1,256}\Z")


def _bad(msg: str) -> StarletteHTTPException:
    return StarletteHTTPException(422, msg)


def _query(request: Request, allowed: set[str] = _ALLOWED_QUERY) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in request.query_params.multi_items():
        if k not in allowed:
            raise _bad(f"Unsupported query parameter: {k}")
        if k == "status" and v not in ("pending", "delivered", "dead"):
            raise _bad("Invalid status")
        if k in ("limit", "page", "page_size") and not (v.isdigit() and 0 < int(v) <= 1000):
            raise _bad(f"Invalid {k}")
        if k == "cursor" and not _CURSOR_RE.match(v):
            raise _bad("Invalid cursor")
        if k == "limit":  # payments paginates with page_size; map the console's limit onto it
            k = "page_size"
            v = str(min(int(v), 100))
        out.append((k, v))
    return out


async def _forward(
    request: Request, method: str, upstream_path: str, params: list[tuple[str, str]], reviewer: str | None = None,
    body: dict | None = None,
) -> Response:
    token = request.app.state.settings.payments_admin_token
    if not token:
        raise StarletteHTTPException(404, "Not Found")
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("accept", "accept-language")}
    headers.update(internal_headers(request, ADMIN_ACTOR))
    headers["X-Admin-Token"] = token
    if reviewer:
        headers["X-Reviewer"] = reviewer
    base = request.app.state.settings.upstream_map()["payments"].rstrip("/")
    try:
        resp = await request.app.state.http.request(
            method, base + upstream_path, params=params, headers=headers, **({"json": body} if body is not None else {})
        )
    except httpx.TimeoutException as e:
        raise UpstreamTimeout("payments") from e
    except httpx.HTTPError as e:
        raise UpstreamUnavailable("payments") from e
    out = {k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "cache-control")}
    return Response(content=resp.content, status_code=resp.status_code, headers=out)


@router.get("/v1/admin/payments/outbox", operation_id="adminPaymentsOutboxList")
async def list_outbox(request: Request) -> Response:
    require_admin(request)
    params = _query(request)
    return await _forward(request, "GET", "/v1/payments/outbox", params)


@router.post("/v1/admin/payments/outbox/{outbox_id}/requeue", operation_id="adminPaymentsOutboxRequeue")
async def requeue_outbox(outbox_id: str, request: Request) -> Response:
    require_admin(request)
    _seg(outbox_id)
    if not _ID_RE.match(outbox_id):
        raise StarletteHTTPException(404, "Not Found")
    if request.query_params:
        raise _bad("Query parameters are not supported")
    return await _forward(request, "POST", f"/v1/payments/outbox/{outbox_id}/requeue", [])


_REVIEW_QUERY = {"limit", "cursor", "page", "page_size"}


@router.get("/v1/admin/payments/review", operation_id="adminPaymentsReviewList")
async def list_review(request: Request) -> Response:
    """Invoices needing a human (late payment / amount mismatch); payments GET /v1/payments/review."""
    require_admin(request)
    params = _query(request, _REVIEW_QUERY)
    reviewer = sanitize_reviewer(request.headers.get("x-reviewer"))
    log.info("admin_action action=payments_review_list reviewer=%s", reviewer)
    return await _forward(request, "GET", "/v1/payments/review", params, reviewer)


_RESOLVE_ACTIONS = ("settle", "refund_flag", "dismiss")
_RESOLVE_KEYS = {"action", "note", "confirm_amount_mismatch", "received_amount"}
_MAX_RESOLVE_BYTES = 4096
_MONEY_RE = re.compile(r"^[0-9]{1,12}(\.[0-9]{1,6})?\Z")
_CUR_RE = re.compile(r"^[A-Z]{3,5}\Z")


async def _resolve_body(request: Request) -> dict:
    """Validate and rebuild the body: only known keys go upstream (payments re-validates everything)."""
    raw = await request.body()
    if len(raw) > _MAX_RESOLVE_BYTES:
        raise StarletteHTTPException(413, "Request body too large")
    try:
        data = json.loads(raw or b"null")
    except ValueError:
        raise _bad("Body must be JSON") from None
    if not isinstance(data, dict) or set(data) - _RESOLVE_KEYS:
        raise _bad("Body must be an object with action, note, confirm_amount_mismatch, received_amount")
    if data.get("action") not in _RESOLVE_ACTIONS:
        raise _bad("action must be settle, refund_flag or dismiss")
    out: dict = {"action": data["action"]}
    note = data.get("note")
    if note is not None:
        if not isinstance(note, str) or len(note) > 500:
            raise _bad("note must be a string of at most 500 characters")
        out["note"] = note
    confirm = data.get("confirm_amount_mismatch", False)
    if not isinstance(confirm, bool):
        raise _bad("confirm_amount_mismatch must be a boolean")
    out["confirm_amount_mismatch"] = confirm
    got = data.get("received_amount")
    if got is not None:
        if (not isinstance(got, dict) or set(got) != {"amount", "currency"} or not isinstance(got["amount"], str)
                or not isinstance(got["currency"], str) or not _MONEY_RE.match(got["amount"])
                or not _CUR_RE.match(got["currency"])):
            raise _bad("received_amount must be {amount: decimal string, currency: ISO code}")
        out["received_amount"] = {"amount": got["amount"], "currency": got["currency"]}
    return out


@router.post("/v1/admin/payments/review/{invoice_id}/resolve", operation_id="adminPaymentsReviewResolve")
async def resolve_review(invoice_id: str, request: Request) -> Response:
    """Resolve a review-queue invoice (settle / refund_flag / dismiss); payments POST /v1/payments/review/{id}/resolve."""
    require_admin(request)
    _seg(invoice_id)
    if not _ID_RE.match(invoice_id):
        raise StarletteHTTPException(404, "Not Found")
    if request.query_params:
        raise _bad("Query parameters are not supported")
    body = await _resolve_body(request)
    reviewer = sanitize_reviewer(request.headers.get("x-reviewer"))
    log.info("admin_action action=payments_review_resolve reviewer=%s invoice=%s resolution=%s confirm_mismatch=%s",
             reviewer, invoice_id, body["action"], body["confirm_amount_mismatch"])
    return await _forward(request, "POST", f"/v1/payments/review/{invoice_id}/resolve", [], reviewer, body)
