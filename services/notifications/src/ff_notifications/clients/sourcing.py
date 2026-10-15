"""Client for the sourcing service: Protocol + httpx implementation + scriptable mock."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, Protocol

import httpx

from ff_notifications.domain.models import ListingView, SearchPage, SearchQuery, TrustBand
from ff_notifications.domain.money import Money, MoneyError


class SourcingUnavailableError(Exception):
    """Sourcing could not answer (network error, 5xx, malformed payload)."""


class SourcingClient(Protocol):
    async def get_listing(self, listing_id: str) -> ListingView | None:
        """The listing, or ``None`` when sourcing answers 404."""
        ...

    async def search(self, query: SearchQuery, page_size: int = 20) -> SearchPage: ...


def listing_from_json(data: dict[str, Any]) -> ListingView:
    try:
        price = data["price"]
        supplier = data["supplier"]
        return ListingView(
            id=data["id"],
            kind=data["kind"],
            title=data["title"],
            title_ar=data.get("title_ar"),
            category=data.get("category"),
            condition=data.get("condition"),
            unit=data.get("unit"),
            price_min=Money.from_json(price["min"]),
            price_max=Money.from_json(price["max"]),
            supplier_id=supplier["id"],
            supplier_name=supplier["name"],
            supplier_verified=bool(supplier.get("verified", False)),
            trust_band=TrustBand.parse(supplier.get("trust_band")),
            origin_country=(data.get("origin") or {}).get("country_code"),
            moq=data.get("moq"),
        )
    except (KeyError, TypeError, MoneyError) as exc:
        raise SourcingUnavailableError(f"malformed listing payload: {exc}") from exc


def _is_degraded(body: dict[str, Any]) -> bool:
    """True when sourcing says the answer is partial or built from substituted results."""
    if body.get("warning"):
        return True
    for src in body.get("sources") or []:
        if isinstance(src, dict) and (src.get("status", "ok") != "ok" or src.get("warning")):
            return True
    return False


class HttpSourcingClient:
    def __init__(
        self, base_url: str, timeout: float = 5.0, client: httpx.AsyncClient | None = None
    ):
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def get_listing(self, listing_id: str) -> ListingView | None:
        try:
            resp = await self._client.get(f"/v1/listings/{listing_id}")
        except httpx.HTTPError as exc:
            raise SourcingUnavailableError(str(exc)) from exc
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise SourcingUnavailableError(f"sourcing returned {resp.status_code}")
        return listing_from_json(resp.json())

    async def search(self, query: SearchQuery, page_size: int = 20) -> SearchPage:
        params = {**query.to_params(), "page": "1", "page_size": str(page_size)}
        try:
            resp = await self._client.get("/v1/search", params=params)
        except httpx.HTTPError as exc:
            raise SourcingUnavailableError(str(exc)) from exc
        if resp.status_code != 200:
            raise SourcingUnavailableError(f"sourcing returned {resp.status_code}")
        try:
            body = resp.json()
            raw_items = body.get("items")
            if not isinstance(raw_items, list):
                # a 200 without an item list is a failure, never "no results"
                raise SourcingUnavailableError("malformed search payload: items missing")
            items = tuple(listing_from_json(i) for i in raw_items)
            total = int(body.get("total", len(items)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise SourcingUnavailableError(f"malformed search payload: {exc}") from exc
        # total > 0 but no items on page 1 is inconsistent: treat as degraded, not as empty
        degraded = _is_degraded(body) or (not items and total > 0)
        return SearchPage(items=items, total=total, degraded=degraded)

    async def aclose(self) -> None:
        await self._client.aclose()


class MockSourcingClient:
    """Deterministic, scriptable sourcing: tests mutate the catalog between evaluations."""

    def __init__(self, listings: list[ListingView] | None = None) -> None:
        self.catalog: dict[str, ListingView] = {item.id: item for item in listings or []}
        self.fail = False
        self.degraded = False
        """Scripted: searches answer with ``SearchPage.degraded`` set (partial_results)."""

    def put(self, listing: ListingView) -> None:
        self.catalog[listing.id] = listing

    def set_price(self, listing_id: str, amount: str | Decimal) -> None:
        item = self.catalog[listing_id]
        money = Money.of(amount, item.price_min.currency)
        self.catalog[listing_id] = replace(
            item, price_min=money, price_max=max(money, item.price_max)
        )

    def remove(self, listing_id: str) -> None:
        self.catalog.pop(listing_id, None)

    async def get_listing(self, listing_id: str) -> ListingView | None:
        if self.fail:
            raise SourcingUnavailableError("scripted failure")
        return self.catalog.get(listing_id)

    async def search(self, query: SearchQuery, page_size: int = 20) -> SearchPage:
        if self.fail:
            raise SourcingUnavailableError("scripted failure")
        hits = []
        for item in self.catalog.values():
            if query.kind and item.kind != query.kind:
                continue
            if query.category and (item.category or "").casefold() != query.category.casefold():
                continue
            if query.condition in ("new", "used") and item.effective_condition != query.condition:
                continue
            if query.max_price is not None and item.price.amount > query.max_price:
                continue
            if query.min_price is not None and item.price.amount < query.min_price:
                continue
            if query.q and query.q.casefold() not in item.title.casefold():
                continue
            hits.append(item)
        hits.sort(key=lambda i: (i.price.amount, i.id))
        return SearchPage(
            items=tuple(hits[:page_size]), total=len(hits), degraded=self.degraded
        )
