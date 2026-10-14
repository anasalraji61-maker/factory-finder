"""Deterministic in-process mocks (no network, no randomness, fixed timestamps)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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
from ff_assistant.domain.models import LandedCostQuote, Listing, TrustScore, band_for_score

_NOW = datetime(2026, 10, 13, tzinfo=UTC)


def _sup(sid: str, name: str, cc: str, city: str, score: int) -> dict:
    return {"id": sid, "name": name, "location": {"country_code": cc, "city": city},
            "verified": score >= 75, "trust_score": score, "trust_band": band_for_score(score).value}


_CATALOG = [
    ("lst_mock_001", "Used pastry production line", "خط إنتاج معجنات مستعمل", "production_line", "used", "pastry production line bakery food machinery", "45000", "60000", 1, "set", 4000, _sup("sup_cn_001", "Guangzhou Bakery Machinery Co.", "CN", "Guangzhou", 82)),
    ("lst_mock_002", "Plastic chair stackable", "كرسي بلاستيك", "product", "new", "plastic chair furniture", "3.2", "4.5", 100, "piece", 4.5, _sup("sup_cn_002", "Foshan Furniture Ltd", "CN", "Foshan", 64)),
    ("lst_mock_003", "Plastic granules PP virgin", "حبيبات بلاستيك", "raw_material", "new", "plastic granules polypropylene plastics", "950", "1100", 1, "ton", 1000, _sup("sup_cn_003", "Ningbo Polymers", "CN", "Ningbo", 88)),
    ("lst_mock_004", "Solar panel 550W mono", "لوح طاقة شمسية", "product", "new", "solar panel energy", "62", "78", 100, "piece", 28, _sup("sup_cn_004", "Jiangsu Solar Tech", "CN", "Changzhou", 79)),
    ("lst_mock_005", "Used CNC machining center", "مركز تشغيل CNC مستعمل", "product", "used", "cnc machine machinery lathe", "18000", "26000", 1, "unit", 3500, _sup("sup_de_001", "Stuttgart Werkzeug GmbH", "DE", "Stuttgart", 91)),
]


def _listing(row: tuple) -> Listing:
    lid, title, ar, kind, cond, kw, lo, hi, moq, unit, kg, sup = row
    cc = sup["location"]["country_code"]
    return Listing.model_validate({
        "id": lid, "source": "mock", "kind": kind, "condition": cond, "title": title, "title_ar": ar,
        "price": {"min": {"amount": lo, "currency": "USD"}, "max": {"amount": hi, "currency": "USD"}},
        "unit": unit, "moq": moq, "unit_weight_kg": kg, "supplier": sup,
        "origin": {"country_code": cc, "city": sup["location"]["city"]}, "category": kw.split()[-1],
    })


class MockSourcingClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def search(self, params: dict[str, Any]) -> SearchResult:
        self.calls.append(params)
        if self.fail:
            raise ClientError("sourcing")
        words = set(str(params.get("q") or "").lower().split())
        out = []
        for row in _CATALOG:
            lst = _listing(row)
            if params.get("kind") and lst.kind.value != params["kind"]:
                continue
            if params.get("condition") not in (None, "any") and lst.condition and lst.condition.value != params["condition"]:
                continue
            if params.get("origin_country") and lst.origin and lst.origin.country_code != params["origin_country"]:
                continue
            if params.get("max_price") is not None and lst.price.min.amount > Decimal(str(params["max_price"])):
                continue
            hay = set(row[5].lower().split())
            if words and not (words & hay):
                continue
            out.append(lst)
        return SearchResult(items=out, total=len(out))


    async def get_listing(self, listing_id: str) -> Listing | None:
        self.calls.append({"get_listing": listing_id})
        if self.fail:
            raise ClientError("sourcing")
        return next((_listing(r) for r in _CATALOG if r[0] == listing_id), None)


_HS = [
    ("392690", "39", "Other articles of plastics", "مصنوعات أخرى من البلاستيك", 10.0, "plastic plastics article chair كرسي بلاستيك"),
    ("940180", "94", "Plastic and other seats", "مقاعد من البلاستيك وغيرها", 20.0, "chair chairs seat seats plastic كرسي كراسي مقعد"),
    ("847130", "84", "Portable automatic data processing machines", "حواسيب محمولة", 5.0, "laptop computer حاسوب"),
    ("390210", "39", "Polypropylene in primary forms", "بولي بروبلين بأشكال أولية", 5.0, "polypropylene plastic granules حبيبات بلاستيك"),
]


class MockLogisticsClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def landed_cost(self, request: dict[str, Any]) -> LandedCostQuote:
        self.calls.append(request)
        if self.fail:
            raise ClientError("logistics")
        goods = request["goods"]
        weight = Decimal(str(goods["total_weight_kg"]))
        value = Decimal(str((goods.get("total_value") or {"amount": "0"})["amount"]))
        sea = (weight * Decimal("0.35") + 600).quantize(Decimal("1"))
        air = (weight * Decimal("4.8") + 150).quantize(Decimal("1"))
        duty = (value * Decimal("0.05")).quantize(Decimal("1"))

        def option(mode: str, freight: Decimal, lo_days: int, hi_days: int, rec: bool) -> dict:
            lines = [
                {"stage": "goods", "description": "Goods value", "amount": {"amount": str(value), "currency": "USD"}, "estimate": False},
                {"stage": "main_leg", "description": "Main freight", "amount": {"amount": str(freight), "currency": "USD"}, "estimate": True},
                {"stage": "duties", "description": "Duties and taxes", "amount": {"amount": str(duty), "currency": "USD"}, "estimate": True},
            ]
            total = value + freight + duty
            return {"mode": mode, "lines": lines, "recommended": rec, "route_summary": f"{mode} route",
                    "total": {"min": {"amount": str((total * Decimal("0.9")).quantize(Decimal("1"))), "currency": "USD"},
                              "max": {"amount": str((total * Decimal("1.15")).quantize(Decimal("1"))), "currency": "USD"}},
                    "transit_days": {"min": lo_days, "max": hi_days}}

        return LandedCostQuote.model_validate({
            "id": "qt_mock_001", "currency": request.get("display_currency", "USD"),
            "origin": request["origin"], "destination": request["destination"],
            "options": [option("sea_lcl", sea, 35, 50, True), option("air", air, 5, 9, False)],
            "assumptions": ["mock rates"], "created_at": _NOW.isoformat(),
        })


    def _hs_entry(self, row: tuple) -> HsEntry:
        return HsEntry(code=row[0], chapter=row[1], description_en=row[2], description_ar=row[3], typical_duty_percent_hint=row[4])

    async def hs_search(self, q: str, destination_country: str = "IQ", limit: int = 5) -> HsResult:
        self.calls.append({"hs_search": q})
        if self.fail:
            raise ClientError("logistics")
        words = set(q.lower().split())
        rows = [r for r in _HS if words & set(r[5].lower().split()) or any(r[0].startswith(w) for w in words)]
        return HsResult(items=[self._hs_entry(r) for r in rows[:limit]], total=len(rows), destination_country=destination_country,
                        disclaimer="Indicative only; confirm with a customs broker.")

    async def hs_detail(self, code: str, destination_country: str = "IQ") -> HsEntry | None:
        self.calls.append({"hs_detail": code})
        if self.fail:
            raise ClientError("logistics")
        row = next((r for r in _HS if r[0] == code[:6]), None)
        return self._hs_entry(row) if row else None


class MockTrustClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def supplier_score(self, supplier_id: str) -> TrustScore:
        if self.fail:
            raise ClientError("trust")
        known = {row[11]["id"]: row[11]["trust_score"] for row in _CATALOG}
        score = known.get(supplier_id)
        if score is None:
            score = 30 + int(hashlib.sha256(supplier_id.encode()).hexdigest(), 16) % 65
        factors = [
            {"key": "years_in_business", "impact": 8, "explanation": "Established supplier", "explanation_ar": "مورد قائم منذ سنوات"},
            {"key": "verification", "impact": 10 if score >= 75 else -5, "explanation": "Verification status",
             "explanation_ar": "موثق من المنصة" if score >= 75 else "غير موثق بالكامل"},
        ]
        return TrustScore.model_validate({"supplier_id": supplier_id, "score": score, "band": band_for_score(score).value, "factors": factors})


def iso6346_valid(code: str) -> bool:
    code = code.upper()
    if len(code) != 11 or not code[:4].isalpha() or not code[4:].isdigit():
        return False
    values, v = {}, 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if v % 11 == 0:
            v += 1
        values[ch] = v
        v += 1
    total = sum((values[c] if i < 4 else int(c)) * 2**i for i, c in enumerate(code[:10]))
    return total % 11 % 10 == int(code[10])


def _demo_shipment() -> ShipmentInfo:
    return ShipmentInfo(
        id="shp_mock_001", reference="CSQU3054383", reference_type="container", mode="sea", status="in_transit",
        progress_percent=55, eta="2026-11-20T00:00:00Z", carrier={"name": "Mock Line", "name_ar": "خط وهمي"},
        origin={"country_code": "CN", "city": "Ningbo"}, destination={"country_code": "IQ", "city": "Basra"},
        events=[{"status": "departed", "description": "Departed Ningbo", "description_ar": "غادرت نينغبو",
                 "timestamp": "2026-10-10T08:00:00Z", "location": {"name": "Ningbo", "name_ar": "نينغبو"}}],
        last_refreshed_at="2026-10-13T00:00:00Z",
    )


class MockTrackingClient:
    """``shipments`` maps (user_id, normalized reference) -> shipment; default: one demo shipment owned by ``u_demo``."""

    def __init__(self, fail: bool = False, shipments: dict[tuple[str, str], ShipmentInfo] | None = None) -> None:
        self.fail = fail
        self.shipments = shipments if shipments is not None else {("u_demo", "CSQU3054383"): _demo_shipment()}
        self.calls: list[tuple[str, str]] = []

    async def find_shipment(self, user_id: str, reference: str) -> ShipmentInfo | None:
        self.calls.append((user_id, reference))
        if self.fail:
            raise ClientError("tracking")
        return self.shipments.get((user_id, reference.replace(" ", "").upper()))

    async def validate(self, reference_type: str, reference: str) -> ReferenceCheck:
        if self.fail:
            raise ClientError("tracking")
        ok = iso6346_valid(reference) if reference_type == "container" else bool(reference)
        return ReferenceCheck(valid=ok, reference_type=reference_type, normalized=reference.upper(),
                              reason=None if ok else "check digit mismatch")


class MockDealsClient:
    """Deals visible only to their parties (mirrors rfq's 404-for-non-parties)."""

    def __init__(self, fail: bool = False, deals: dict[str, DealInfo] | None = None) -> None:
        self.fail = fail
        self.deals = deals if deals is not None else {"deal_mock_001": DealInfo(
            id="deal_mock_001", buyer_id="u_demo", supplier_user_id="u_supplier", status="pending_payment", quantity="500",
            unit_price={"amount": "3.8", "currency": "USD"}, subtotal={"amount": "1900.00", "currency": "USD"},
            commission={"rate": "0.03", "amount": {"amount": "57.00", "currency": "USD"}, "is_estimate": False},
            payment={"commission": "open", "deal_payment": None}, updated_at="2026-10-13T00:00:00Z")}
        self.calls: list[tuple[str, str]] = []

    async def get_deal(self, user_id: str, deal_id: str) -> DealInfo | None:
        self.calls.append((user_id, deal_id))
        if self.fail:
            raise ClientError("deals")
        d = self.deals.get(deal_id)
        return d if d and user_id in (d.buyer_id, d.supplier_user_id) else None


def build_mock_clients() -> Clients:
    return Clients(sourcing=MockSourcingClient(), logistics=MockLogisticsClient(), trust=MockTrustClient(),
                   tracking=MockTrackingClient(), deals=MockDealsClient())
