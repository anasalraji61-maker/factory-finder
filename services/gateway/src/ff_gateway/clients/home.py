"""Home-feed aggregation client: Protocol + http + mock."""

import asyncio
import time
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
            "degraded": [],
        }


class HttpHomeClient:
    """Calls sourcing (categories, trending) and logistics (fx) concurrently, each with its own timeout.

    A failing or slow section becomes null + a warning and is named in ``degraded``; successful sections are cached for
    a short TTL so a slow upstream does not stall every request.
    """

    def __init__(
        self, http: httpx.AsyncClient, upstreams: dict[str, str], *, timeout: float = 1.5, cache_ttl: float = 15.0
    ) -> None:
        self._http, self._up = http, upstreams
        self._timeout, self._ttl = timeout, cache_ttl
        self._cache: dict[tuple, tuple[float, Any]] = {}

    async def _get(
        self, service: str, path: str, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> Any:
        r = await self._http.get(self._up[service] + path, params=params, headers=headers)
        r.raise_for_status()
        return r.json()

    async def _section(self, key: tuple, coro: Any) -> Any:
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            coro.close()
            return hit[1]
        value = await asyncio.wait_for(coro, self._timeout)
        if self._ttl > 0:
            if len(self._cache) > 64:
                self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            self._cache[key] = (now + self._ttl, value)
        return value

    async def fetch(
        self, *, display_currency: str, destination_country: str | None, headers: dict[str, str]
    ) -> dict[str, Any]:
        calls = {
            "categories": self._section(("categories",), self._get("sourcing", "/v1/categories", headers)),
            "trending": self._section(
                ("trending",), self._get("sourcing", "/v1/search", headers, {"q": "", "page_size": 10})
            ),
            "fx": self._section(
                ("fx", display_currency), self._get("logistics", "/v1/fx/rates", headers, {"base": display_currency})
            ),
        }
        results = await asyncio.gather(*calls.values(), return_exceptions=True)
        out: dict[str, Any] = {"warnings": [], "degraded": []}
        for key, res in zip(calls, results, strict=True):
            if isinstance(res, BaseException):
                out[key] = None
                out["warnings"].append({"section": key, "message": "section unavailable"})
                out["degraded"].append(key)
            else:
                out[key] = (
                    res.get("items", res) if key == "trending" and isinstance(res, dict) else res
                )
        return out
