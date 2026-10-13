"""Client protocols for the services the assistant orchestrates (no business logic here)."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from ff_assistant.domain.models import LandedCostQuote, Listing, TrustScore


class ClientError(Exception):
    """A downstream service failed or timed out (the orchestrator degrades gracefully)."""

    def __init__(self, service: str, message: str = "unavailable") -> None:
        super().__init__(f"{service}: {message}")
        self.service = service


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[Listing]
    total: int = 0


class ReferenceCheck(BaseModel):
    model_config = ConfigDict(extra="allow")

    valid: bool
    reference_type: str | None = None
    normalized: str | None = None
    reason: str | None = None


class SourcingClient(Protocol):
    async def search(self, params: dict[str, Any]) -> SearchResult: ...


class LogisticsClient(Protocol):
    async def landed_cost(self, request: dict[str, Any]) -> LandedCostQuote: ...


class TrustClient(Protocol):
    async def supplier_score(self, supplier_id: str) -> TrustScore: ...


class TrackingClient(Protocol):
    async def validate(self, reference_type: str, reference: str) -> ReferenceCheck: ...


class Clients(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    sourcing: Any
    logistics: Any
    trust: Any
    tracking: Any
