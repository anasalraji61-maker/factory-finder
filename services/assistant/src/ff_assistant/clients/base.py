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


class ShipmentInfo(BaseModel):
    """Subset of tracking's Shipment (tolerant: unknown fields are kept but never rendered)."""

    model_config = ConfigDict(extra="allow")

    id: str
    reference: str
    reference_type: str | None = None
    mode: str | None = None
    status: str
    progress_percent: int = 0
    eta: str | None = None
    label: str | None = None
    carrier: dict[str, Any] | None = None
    origin: dict[str, Any] | None = None
    destination: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []
    delayed: bool | None = None
    delay_hours: int | None = None
    warning: str | None = None
    last_refreshed_at: str | None = None


class DealInfo(BaseModel):
    """Subset of rfq's Deal. Party ids are only used for a defensive ownership check."""

    model_config = ConfigDict(extra="ignore")

    id: str
    buyer_id: str | None = None
    supplier_user_id: str | None = None
    status: str
    quantity: str | None = None
    unit_price: dict[str, Any] | None = None
    subtotal: dict[str, Any] | None = None
    commission: dict[str, Any] | None = None
    supplier_net: dict[str, Any] | None = None
    payment: dict[str, Any] | None = None
    delivered_at: str | None = None
    completed_at: str | None = None
    updated_at: str | None = None


class HsEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    chapter: str | None = None
    description_en: str = ""
    description_ar: str = ""
    typical_duty_percent_hint: float | None = None


class HsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[HsEntry] = []
    total: int = 0
    destination_country: str | None = None
    disclaimer: str | None = None


class SourcingClient(Protocol):
    async def search(self, params: dict[str, Any]) -> SearchResult: ...
    async def get_listing(self, listing_id: str) -> Listing | None: ...


class LogisticsClient(Protocol):
    async def landed_cost(self, request: dict[str, Any]) -> LandedCostQuote: ...
    async def hs_search(self, q: str, destination_country: str = "IQ", limit: int = 5) -> HsResult: ...
    async def hs_detail(self, code: str, destination_country: str = "IQ") -> HsEntry | None: ...


class TrustClient(Protocol):
    async def supplier_score(self, supplier_id: str) -> TrustScore: ...


class TrackingClient(Protocol):
    async def validate(self, reference_type: str, reference: str) -> ReferenceCheck: ...
    async def find_shipment(self, user_id: str, reference: str) -> ShipmentInfo | None:
        """The caller's own shipment with this reference (tracking scopes by X-User-Id), else None."""
        ...


class DealsClient(Protocol):
    async def get_deal(self, user_id: str, deal_id: str) -> DealInfo | None:
        """None when the deal does not exist OR the user is not a party (rfq answers 404 for both)."""
        ...


class Clients(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    sourcing: Any
    logistics: Any
    trust: Any
    tracking: Any
    deals: Any = None  # optional: rfq (deal/payment status); None => deals_unavailable
