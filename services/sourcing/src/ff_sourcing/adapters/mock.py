"""Deterministic mock adapter backed by data/catalog.json (no network)."""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from importlib import resources

from ..domain.models import (
    DayRange,
    GeoPoint,
    ListingDetail,
    Location,
    Money,
    MoneyRange,
    SearchQuery,
    Supplier,
    SupplierSummary,
)
from .base import Health, SourceAdapter


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    with resources.files("ff_sourcing.data").joinpath("catalog.json").open(encoding="utf-8") as f:
        return json.load(f)


class MockAdapter(SourceAdapter):
    id = "mock"
    name = "Mock catalog"
    mode = "mock"
    compliance = "Bundled static data; no network."

    def __init__(self, catalog: dict | None = None):
        cat = catalog or load_catalog()
        self._suppliers = {
            s["id"]: SupplierSummary(
                id=s["id"],
                name=s["name"],
                name_ar=s["name_ar"],
                location=Location(
                    country_code=s["country_code"],
                    city=s["city"],
                    point=GeoPoint(lat=s["lat"], lon=s["lon"]),
                ),
                years_in_business=s["years_in_business"],
                verified=s["verified"],
            )
            for s in cat["suppliers"]
        }
        self._certs = {s["id"]: s.get("certifications", []) for s in cat["suppliers"]}
        self._listings = [self._build(r) for r in cat["listings"]]
        self._by_id = {item.id: item for item in self._listings}

    def _build(self, r: dict) -> ListingDetail:
        sup = self._suppliers[r["supplier_id"]]
        cur = r["currency"]
        cond = {"new": "New", "used": "Used", "refurbished": "Refurbished"}[r["condition"]]
        return ListingDetail(
            id=r["id"],
            source=self.id,
            source_url=f"https://example.com/mock/listings/{r['id']}",
            kind=r["kind"],
            condition=r["condition"],
            title=r["title"],
            title_ar=r["title_ar"],
            category=r["category"],
            images=[
                f"https://picsum.photos/seed/{r['id']}/600/600",
                f"https://picsum.photos/seed/{r['id']}_2/600/600",
            ],
            price=MoneyRange(
                min=Money(amount=Decimal(r["price_min"]), currency=cur),
                max=Money(amount=Decimal(r["price_max"]), currency=cur),
            ),
            unit=r["unit"],
            moq=r["moq"],
            incoterm=r["incoterm"],
            unit_weight_kg=r["unit_weight_kg"],
            unit_volume_m3=r["unit_volume_m3"],
            hs_code=r["hs_code"],
            lead_time_days=DayRange(min=r["lead_time_days"][0], max=r["lead_time_days"][1]),
            supplier=sup,
            origin=sup.location,
            description=(
                f"{r['title']}. {cond}, supplied by {sup.name} ({sup.location.city}, "
                f"{sup.location.country_code}). MOQ {r['moq']} {r['unit']}, {r['incoterm']}."
            ),
            description_ar=f"{r['title_ar']}. المورد: {sup.name_ar}. الحد الأدنى للطلب {r['moq']} {r['unit']}.",
            specs={
                "HS code": r["hs_code"],
                "Condition": cond,
                "Incoterm": r["incoterm"],
                "Unit weight (kg)": str(r["unit_weight_kg"]),
                "Unit volume (m3)": str(r["unit_volume_m3"]),
            },
        )

    async def search(self, query: SearchQuery) -> list[ListingDetail]:
        out = self._listings
        if query.kind:
            out = [i for i in out if i.kind == query.kind]
        if query.origin_country:
            out = [
                i for i in out if i.supplier.location.country_code == query.origin_country.upper()
            ]
        # shared, read-only: the service shallow-copies the items it keeps before enriching them
        return list(out)

    async def get_listing(self, listing_id: str) -> ListingDetail | None:
        item = self._by_id.get(listing_id)
        return item.model_copy(deep=True) if item else None

    async def get_supplier(self, supplier_id: str) -> Supplier | None:
        s = self._suppliers.get(supplier_id)
        if s is None:
            return None
        n = sum(1 for i in self._listings if i.supplier.id == supplier_id)
        return Supplier(
            **s.model_dump(),
            certifications=self._certs[supplier_id],
            listing_count=n,
            source=self.id,
        )

    async def health(self) -> Health:
        return Health(ok=True, detail=f"{len(self._listings)} listings")
