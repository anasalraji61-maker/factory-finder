"""Client for the rfq service (deal ownership): Protocol + httpx + deterministic mock."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from ff_payments.domain.errors import UpstreamUnavailable


class DealClient(Protocol):
    async def get_deal(self, deal_id: str, user_id: str) -> dict[str, Any] | None:
        """The rfq ``Deal`` as seen by ``user_id`` (None when missing or not theirs)."""
        ...


class HttpDealClient:
    def __init__(self, base_url: str, internal_token: str | None = None, timeout: float = 5.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._token = internal_token
        self._c = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    async def get_deal(self, deal_id: str, user_id: str) -> dict[str, Any] | None:
        headers = {"X-User-Id": user_id}
        if self._token:
            headers["X-Internal-Token"] = self._token
        try:
            r = await self._c.get(f"/v1/deals/{deal_id}", headers=headers)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable("RFQ service unavailable") from exc
        if r.status_code in (403, 404):
            return None
        try:
            r.raise_for_status()
            return dict(r.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamUnavailable("RFQ service unavailable") from exc

    async def aclose(self) -> None:
        await self._c.aclose()


class MockDealClient:
    def __init__(self, deals: dict[str, dict[str, Any]] | None = None) -> None:
        self.deals = deals if deals is not None else {}

    async def get_deal(self, deal_id: str, user_id: str) -> dict[str, Any] | None:
        d = self.deals.get(deal_id)
        return d if d and user_id in (d.get("buyer_id"), d.get("supplier_user_id")) else None
