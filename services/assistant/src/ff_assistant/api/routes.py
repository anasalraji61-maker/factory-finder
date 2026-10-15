from __future__ import annotations

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


@router.post("/query", response_model=AssistantResult, response_model_exclude_none=True,
             responses={429: {"description": "Daily per-user quota exceeded (code quota_exceeded, Retry-After)"}})
async def query(body: AssistantRequest, request: Request, response: Response):
    user_id = caller_id(request)
    decision = request.app.state.quota.hit(user_id, request.client.host if request.client else "unknown")
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
            "data": {"quota_used_today": request.app.state.quota.usage(user_id), "conversations_stored": False}}  # fmt: skip


@internal.delete("/users/{user_id}/data")
async def erase_user(user_id: str, request: Request) -> dict:
    return {"service": "assistant", "user_id": user_id, "status": "done",
            "counts": {"quota_counters_removed": request.app.state.quota.forget(user_id)}}  # fmt: skip
