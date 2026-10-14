"""httpx clients; every failure is normalized to :class:`ClientError`."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from ff_assistant.clients.base import (
    ClientError,
    Clients,
    DealInfo,
    HsEntry,
    HsResult,
    ReferenceCheck,
    SearchResult,
    ShipmentInfo,
)
from ff_assistant.config import Settings
from ff_assistant.domain.models import LandedCostQuote, Listing, TrustScore


class _Base:
    service = "service"

    def __init__(self, base_url: str, timeout: float, token: str | None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        headers = {"X-Internal-Token": token} if token else {}
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout, headers=headers, transport=transport)

    async def _call(self, method: str, url: str, *, none_on_404: bool = False, **kw: Any) -> Any:
        try:
            resp = await self._http.request(method, url, **kw)
            if none_on_404 and resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ClientError(self.service, type(exc).__name__) from exc

    def _parse[T](self, model: type[T], data: Any) -> T:
        try:
            return model.model_validate(data)  # type: ignore[attr-defined]
        except ValidationError as exc:
            raise ClientError(self.service, "bad response") from exc

    async def aclose(self) -> None:
        await self._http.aclose()


class HttpSourcingClient(_Base):
    service = "sourcing"

    async def search(self, params: dict[str, Any]) -> SearchResult:
        clean = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in params.items() if v is not None}
        return self._parse(SearchResult, await self._call("GET", "/v1/search", params=clean))

    async def get_listing(self, listing_id: str) -> Listing | None:
        data = await self._call("GET", f"/v1/listings/{quote(listing_id, safe='')}", none_on_404=True)
        return None if data is None else self._parse(Listing, data)


class HttpLogisticsClient(_Base):
    service = "logistics"

    async def landed_cost(self, request: dict[str, Any]) -> LandedCostQuote:
        return self._parse(LandedCostQuote, await self._call("POST", "/v1/quotes/landed-cost", json=request))

    async def hs_search(self, q: str, destination_country: str = "IQ", limit: int = 5) -> HsResult:
        params = {"q": q, "limit": limit, "destination_country": destination_country}
        return self._parse(HsResult, await self._call("GET", "/v1/hs/search", params=params))

    async def hs_detail(self, code: str, destination_country: str = "IQ") -> HsEntry | None:
        data = await self._call("GET", f"/v1/hs/{quote(code, safe='')}", params={"destination_country": destination_country}, none_on_404=True)
        return None if data is None else self._parse(HsEntry, data)


class HttpTrustClient(_Base):
    service = "trust"

    async def supplier_score(self, supplier_id: str) -> TrustScore:
        return self._parse(TrustScore, await self._call("GET", f"/v1/trust/suppliers/{quote(supplier_id, safe='')}"))


class HttpTrackingClient(_Base):
    service = "tracking"

    async def validate(self, reference_type: str, reference: str) -> ReferenceCheck:
        return self._parse(ReferenceCheck, await self._call("GET", f"/v1/validate/{quote(reference_type, safe='')}/{quote(reference, safe='')}"))


    async def find_shipment(self, user_id: str, reference: str) -> ShipmentInfo | None:
        """List the caller's shipments (tracking filters by X-User-Id) and match the normalized reference."""
        want = "".join(reference.split()).upper()
        for page in (1, 2, 3):
            data = await self._call("GET", "/v1/shipments", params={"page": page, "page_size": 100}, headers={"X-User-Id": user_id})
            items = data.get("items", []) if isinstance(data, dict) else []
            for it in items:
                if isinstance(it, dict) and "".join(str(it.get("reference", "")).split()).upper() == want:
                    return self._parse(ShipmentInfo, it)
            if len(items) < 100:
                break
        return None


class HttpDealsClient(_Base):
    service = "deals"

    async def get_deal(self, user_id: str, deal_id: str) -> DealInfo | None:
        data = await self._call("GET", f"/v1/deals/{quote(deal_id, safe='')}", headers={"X-User-Id": user_id}, none_on_404=True)
        return None if data is None else self._parse(DealInfo, data)


def build_http_clients(s: Settings, transport: httpx.AsyncBaseTransport | None = None) -> Clients:
    token = s.internal_token.get_secret_value() if s.internal_token else None
    t = s.http_timeout_s
    return Clients(
        sourcing=HttpSourcingClient(s.sourcing_url, t, token, transport),
        logistics=HttpLogisticsClient(s.logistics_url, t, token, transport),
        trust=HttpTrustClient(s.trust_url, t, token, transport),
        tracking=HttpTrackingClient(s.tracking_url, t, token, transport),
        deals=HttpDealsClient(s.rfq_url, t, token, transport),
    )
