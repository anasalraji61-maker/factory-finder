"""Client for the sourcing service (matching suggestions): Protocol + httpx + deterministic mock."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from ff_rfq.domain.errors import UpstreamUnavailable


class SourcingClient(Protocol):
    async def search(self, query: str, kind: str | None, condition: str | None, limit: int) -> list[dict[str, Any]]:
        """Return common-schema ``Listing`` dicts matching a request."""
        ...


class HttpSourcingClient:
    def __init__(self, base_url: str, timeout: float = 5.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    async def search(self, query: str, kind: str | None, condition: str | None, limit: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"q": query, "page_size": limit}
        if kind:
            params["kind"] = kind
        if condition and condition != "any":
            params["condition"] = condition
        try:
            resp = await self._client.get("/v1/search", params=params)
            resp.raise_for_status()
            return list(resp.json()["items"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise UpstreamUnavailable("Sourcing service unavailable") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


class MockSourcingClient:
    """Deterministic: returns ``limit`` (max 3) listings derived from the query."""

    async def search(self, query: str, kind: str | None, condition: str | None, limit: int) -> list[dict[str, Any]]:
        return [
            {
                "id": f"lst_mock{i}", "source": "mock", "kind": kind or "product", "title": f"{query} #{i}",
                "condition": "new" if condition in (None, "any") else condition,
                "price": {"min": {"amount": "1.00", "currency": "USD"}, "max": {"amount": "2.00", "currency": "USD"}},
                "supplier": {"id": f"sup_mock{i}", "name": f"Mock Supplier {i}", "location": {"country_code": "CN"}},
            }
            for i in range(1, min(limit, 3) + 1)
        ]
