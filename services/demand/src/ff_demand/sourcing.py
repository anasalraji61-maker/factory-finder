"""Sourcing client: Protocol + httpx implementation + deterministic mock."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx


class SourcingUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    title_ar: str | None
    supplier_name: str
    price_min: Decimal
    price_max: Decimal
    currency: str


class SourcingClient(Protocol):
    async def search(
        self, query: str, origin_country: str | None, limit: int
    ) -> list[Candidate]: ...


def candidate_from_json(d: dict) -> Candidate:
    try:
        p = d["price"]
        return Candidate(
            id=d["id"],
            title=d["title"],
            title_ar=d.get("title_ar"),
            supplier_name=d["supplier"]["name"],
            price_min=Decimal(str(p["min"]["amount"])),
            price_max=Decimal(str(p["max"]["amount"])),
            currency=p["min"]["currency"],
        )
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise SourcingUnavailableError(f"malformed listing: {exc}") from exc


class HttpSourcingClient:
    def __init__(
        self, base_url: str, timeout: float = 5.0, client: httpx.AsyncClient | None = None
    ):
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def search(self, query: str, origin_country: str | None, limit: int) -> list[Candidate]:
        params = {"q": query, "page": "1", "page_size": str(limit)}
        if origin_country:
            params["origin_country"] = origin_country
        try:
            resp = await self._client.get("/v1/search", params=params)
        except httpx.HTTPError as exc:
            raise SourcingUnavailableError(str(exc)) from exc
        if resp.status_code != 200:
            raise SourcingUnavailableError(f"sourcing returned {resp.status_code}")
        return [candidate_from_json(i) for i in resp.json().get("items", [])][:limit]

    async def aclose(self) -> None:
        await self._client.aclose()


_MOCK = [
    Candidate(
        "lst_pack_1",
        "Automatic bottle filling machine",
        "ماكنة تعبئة قناني أوتوماتيكية",
        "Shenzhen Packtech",
        Decimal("3500"),
        Decimal("4200"),
        "USD",
    ),
    Candidate(
        "lst_pack_2",
        "Semi-automatic liquid filling machine",
        "ماكنة تعبئة سوائل نصف أوتوماتيكية",
        "Guangzhou FillCo",
        Decimal("1800"),
        Decimal("2100"),
        "USD",
    ),
    Candidate(
        "lst_pump_1",
        "Centrifugal water pump",
        "مضخة مياه طرد مركزي",
        "Ningbo Pumps",
        Decimal("120"),
        Decimal("150"),
        "USD",
    ),
]
_MOCK_KEYS = {
    "lst_pack_1": ("تعبئة", "filling", "packag", "مكائن", "ماكنة"),
    "lst_pack_2": ("تعبئة", "filling", "packag", "مكائن", "ماكنة"),
    "lst_pump_1": ("مضخ", "pump"),
}


class MockSourcingClient:
    """Keyword match over a tiny fixed catalog; ``fail`` scripts an outage."""

    def __init__(self, catalog: list[Candidate] | None = None):
        self.catalog = list(_MOCK if catalog is None else catalog)
        self.fail = False

    async def search(self, query: str, origin_country: str | None, limit: int) -> list[Candidate]:
        if self.fail:
            raise SourcingUnavailableError("scripted failure")
        q = query.casefold()
        hits = [
            c
            for c in self.catalog
            if any(k in q for k in _MOCK_KEYS.get(c.id, ())) or c.title.casefold() in q
        ]
        return sorted(hits, key=lambda c: (c.price_min, c.id))[:limit]
