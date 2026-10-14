"""Home-feed aggregation client: Protocol + http + mock."""

import asyncio
from typing import Any, Protocol

import httpx


class HomeClient(Protocol):
    async def fetch(
        self, *, display_currency: str, destination_country: str | None, headers: dict[str, str]
    ) -> dict[str, Any]: ...


class MockHomeClient:
    async def fetch(
        self, *, display_currency: str, destination_country: str | None, headers: dict[str, str]
    ) -> dict[str, Any]:
        return {
            "categories": [
                {"id": "cat_electronics", "name": "Electronics", "name_ar": "إلكترونيات"}
            ],
            "trending": [{"id": "lst_mock_1", "title": "Mock trending item"}],
            "fx": {"base": display_currency, "rates": {"USD": "1.00"}},
            "warnings": [],
        }


class HttpHomeClient:
    """Calls sourcing (categories, trending) and logistics (fx); a failing section becomes null + warning."""

    def __init__(self, http: httpx.AsyncClient, upstreams: dict[str, str]) -> None:
        self._http, self._up = http, upstreams

    async def _get(
        self, service: str, path: str, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> Any:
        r = await self._http.get(self._up[service] + path, params=params, headers=headers)
        r.raise_for_status()
        return r.json()

    async def fetch(
        self, *, display_currency: str, destination_country: str | None, headers: dict[str, str]
    ) -> dict[str, Any]:
        calls = {
            "categories": self._get("sourcing", "/v1/categories", headers),
            "trending": self._get("sourcing", "/v1/search", headers, {"q": "", "page_size": 10}),
            "fx": self._get("logistics", "/v1/fx/rates", headers, {"base": display_currency}),
        }
        results = await asyncio.gather(*calls.values(), return_exceptions=True)
        out: dict[str, Any] = {"warnings": []}
        for key, res in zip(calls, results, strict=True):
            if isinstance(res, BaseException):
                out[key] = None
                out["warnings"].append({"section": key, "message": "section unavailable"})
            else:
                out[key] = (
                    res.get("items", res) if key == "trending" and isinstance(res, dict) else res
                )
        return out
