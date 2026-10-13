from __future__ import annotations

from fastapi import APIRouter, Request

from ff_assistant.api.schemas import AssistantRequest
from ff_assistant.service import Assistant, AssistantResult

router = APIRouter(prefix="/v1/assistant", tags=["assistant"])


@router.post("/query", response_model=AssistantResult, response_model_exclude_none=True)
async def query(body: AssistantRequest, request: Request) -> AssistantResult:
    assistant: Assistant = request.app.state.assistant
    return await assistant.handle(body.text, body.destination)
