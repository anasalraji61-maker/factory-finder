"""httpx clients; every failure is normalized to :class:`ClientError`."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from ff_assistant.clients.base import ClientError, Clients, ReferenceCheck, SearchResult
from ff_assistant.config import Settings
from ff_assistant.domain.models import LandedCostQuote, TrustScore


class _Base:
    service = "service"

    def __init__(self, base_url: str, timeout: float, token: str | None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        headers = {"X-Internal-Token": token} if token else {}
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout, headers=headers, transport=transport)

    async def _call(self, method: str, url: str, **kw: Any) -> Any:
        try:
            resp = await self._http.request(method, url, **kw)
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


class HttpLogisticsClient(_Base):
    service = "logistics"

    async def landed_cost(self, request: dict[str, Any]) -> LandedCostQuote:
        return self._parse(LandedCostQuote, await self._call("POST", "/v1/quotes/landed-cost", json=request))


class HttpTrustClient(_Base):
    service = "trust"

    async def supplier_score(self, supplier_id: str) -> TrustScore:
        return self._parse(TrustScore, await self._call("GET", f"/v1/trust/suppliers/{quote(supplier_id, safe='')}"))


class HttpTrackingClient(_Base):
    service = "tracking"

    async def validate(self, reference_type: str, reference: str) -> ReferenceCheck:
        return self._parse(ReferenceCheck, await self._call("GET", f"/v1/validate/{quote(reference_type, safe='')}/{quote(reference, safe='')}"))


def build_http_clients(s: Settings, transport: httpx.AsyncBaseTransport | None = None) -> Clients:
    token = s.internal_token.get_secret_value() if s.internal_token else None
    t = s.http_timeout_s
    return Clients(
        sourcing=HttpSourcingClient(s.sourcing_url, t, token, transport),
        logistics=HttpLogisticsClient(s.logistics_url, t, token, transport),
        trust=HttpTrustClient(s.trust_url, t, token, transport),
        tracking=HttpTrackingClient(s.tracking_url, t, token, transport),
    )
