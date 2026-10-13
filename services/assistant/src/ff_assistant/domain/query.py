"""Structured result of parsing a user message (pure data)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from ff_assistant.domain.models import (
    Condition,
    CurrencyCode,
    DecimalStr,
    ListingKind,
    Location,
)


class Intent(StrEnum):
    SEARCH = "search"
    QUOTE = "quote"
    TRUST = "trust"
    TRACK = "track"
    HELP = "help"


class Budget(BaseModel):
    amount: DecimalStr
    currency: CurrencyCode
    bound: Literal["max", "min"] = "max"


class ParsedQuery(BaseModel):
    intent: Intent
    language: Literal["ar", "en"] = "ar"
    kind: ListingKind | None = None
    condition: Condition | None = None
    keywords: list[str] = Field(default_factory=list)
    query: str = ""
    category: str | None = None
    quantity: DecimalStr | None = None
    unit: str | None = None
    budget: Budget | None = None
    origin: Location | None = None
    origin_region: str | None = None
    destination: Location | None = None
    supplier_id: str | None = None
    reference: str | None = None
    reference_type: Literal["container", "awb", "vessel_imo"] | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
