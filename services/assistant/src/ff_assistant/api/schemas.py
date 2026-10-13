from __future__ import annotations

from pydantic import BaseModel, Field

from ff_assistant.domain.models import Locale, Location


class AssistantRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    locale: Locale = "ar"
    destination: Location | None = None
