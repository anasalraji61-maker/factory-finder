from __future__ import annotations

import hmac
import ipaddress
import re

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ff_assistant.api.schemas import AssistantRequest
from ff_assistant.service import Assistant, AssistantResult

router = APIRouter(prefix="/v1/assistant", tags=["assistant"])

_UID = re.compile(r"^[A-Za-z0-9_.:@-]{1,64}$")


def caller_id(request: Request) -> str | None:
    """Identity = X-User-Id set by the gateway (never taken from the message text); malformed => anonymous."""
    raw = request.headers.get("X-User-Id", "").strip()
    return raw if _UID.fullmatch(raw) else None


def quota_client(request: Request) -> str:
    """Anonymous quota key: the peer address, unless X-Client-Ip (set by the gateway) is trustworthy: the request
    presented the valid internal token, or the deployment explicitly trusts the proxy. Value must be a bare IP."""
    peer = request.client.host if request.client else "unknown"
    s = request.app.state.settings
    token = s.internal_token.get_secret_value() if s.internal_token else None
    presented = request.headers.get("X-Internal-Token", "")
    if not (s.trust_client_ip_header or (token and hmac.compare_digest(presented.encode(), token.encode()))):
        return peer
    raw = request.headers.get("X-Client-Ip", "").strip()
    try:
        return str(ipaddress.ip_address(raw)) if raw else peer
    except ValueError:
        return peer


@router.post("/query", response_model=AssistantResult, response_model_exclude_none=True,
             responses={429: {"description": "Daily per-user quota exceeded (code quota_exceeded, Retry-After)"}})
async def query(body: AssistantRequest, request: Request, response: Response):
    user_id = caller_id(request)
    burst = request.app.state.burst.hit(user_id, quota_client(request))
    if not burst.allowed:
        return JSONResponse(
            status_code=429, headers={"Retry-After": str(burst.retry_after_s)},
            content={"error": {"code": "rate_limited", "message": "too many requests, slow down",
                               "details": {"limit_per_minute": burst.limit, "retry_after_seconds": burst.retry_after_s}}},
        )
    decision = await request.app.state.quota.ahit(user_id, quota_client(request))
    if not decision.allowed:
        return JSONResponse(
            status_code=429, headers={"Retry-After": str(decision.retry_after_s)},
            content={"error": {"code": "quota_exceeded", "message": "daily assistant quota exceeded",
                               "details": {"limit": decision.limit, "retry_after_seconds": decision.retry_after_s}}},
        )
    response.headers["X-Quota-Remaining"] = str(decision.remaining)
    assistant: Assistant = request.app.state.assistant
    return await assistant.handle(body.text, body.destination, user_id)


internal = APIRouter(prefix="/v1/internal", tags=["internal"])


@internal.post("/users/{user_id}/export")
async def export_user(user_id: str, request: Request) -> dict:
    """Account export (internal token only). The assistant stores no conversations; only the daily quota counter exists."""
    return {"service": "assistant", "user_id": user_id, "truncated": False,
            "data": {"quota_used_today": await request.app.state.quota.ausage(user_id), "conversations_stored": False}}  # fmt: skip


@internal.delete("/users/{user_id}/data")
async def erase_user(user_id: str, request: Request) -> dict:
    return {"service": "assistant", "user_id": user_id, "status": "done",
            "counts": {"quota_counters_removed": await request.app.state.quota.aforget(user_id)}}  # fmt: skip
