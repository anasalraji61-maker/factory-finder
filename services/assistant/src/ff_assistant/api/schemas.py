from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from ff_assistant.domain.models import Locale, Location


class AssistantRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    locale: Locale = "ar"
    destination: Location | None = None

    @field_validator("destination")
    @classmethod
    def _bounded_destination(cls, v: Location | None) -> Location | None:
        if v is not None and v.city is not None and len(v.city) > 80:
            raise ValueError("destination.city is too long (max 80)")
        return v
