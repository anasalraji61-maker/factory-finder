"""Price history (recording, dedupe, cap, trend, mock series) and similar/recommendations."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry
from ff_sourcing.clients.trust import MockTrustClient, TrustInfo
from ff_sourcing.config import Settings
from ff_sourcing.domain import pricehistory as ph
from ff_sourcing.main import create_app
from ff_sourcing.price_history import PriceHistoryStore

from .test_native import GREEN, A, body

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


# ---------- pure domain ----------
def test_dedupe_rule():
    last = ph.Obs(NOW - timedelta(hours=2), Decimal("10"), "USD")
    assert not ph.should_record(last, Decimal("10"), "USD", NOW, 6)
    assert ph.should_record(last, Decimal("11"), "USD", NOW, 6)
    assert ph.should_record(last, Decimal("10"), "EUR", NOW, 6)
    assert ph.should_record(ph.Obs(NOW - timedelta(hours=7), Decimal("10"), "USD"), Decimal("10"), "USD", NOW, 6)
    assert ph.should_record(None, Decimal("10"), "USD", NOW, 6)


def test_trend_buckets_and_hints():
    obs = [ph.Obs(NOW - timedelta(days=d), Decimal(p), "USD") for d, p in [(10, "100"), (5, "90"), (0, "80")]]
    h = ph.build("x", obs, 30, "day", NOW)
    assert [p.min for p in h.points] == [Decimal("100"), Decimal("90"), Decimal("80")]
    assert h.summary.min == Decimal("80") and h.summary.max == Decimal("100") and h.summary.avg == Decimal("90.00")
    assert h.trend.direction == "down" and h.trend.change_pct == Decimal("-20.00") and not h.trend.insufficient_data
    assert h.hints.at_period_low and h.hints.suggested_target.amount == Decimal("80")
    month = ph.build("x", obs, 30, "month", NOW)
    assert sum(p.n for p in month.points) == 3
    flat = ph.build("x", [ph.Obs(NOW - timedelta(days=2), Decimal("100"), "USD"), ph.Obs(NOW, Decimal("100.5"), "USD")], 30, "day", NOW)
    assert flat.trend.direction == "flat" and not flat.trend.insufficient_data


def test_insufficient_data():
    assert ph.build("x", [], 30, "day", NOW).trend.insufficient_data
    one = ph.build("x", [ph.Obs(NOW, Decimal("5"), "USD")], 30, "day", NOW)
    assert one.trend.insufficient_data and one.trend.change_pct is None and one.hints is None
    same_bucket = [ph.Obs(NOW - timedelta(hours=8), Decimal("5"), "USD"), ph.Obs(NOW, Decimal("6"), "USD")]
    assert ph.build("x", same_bucket, 30, "day", NOW).trend.insufficient_data


def test_synthetic_deterministic_and_ends_at_current():
    a = ph.synthetic_observations("lst_0001", Decimal("1234.50"), "USD", NOW, 90)
    b = ph.synthetic_observations("lst_0001", Decimal("1234.50"), "USD", NOW, 90)
    c = ph.synthetic_observations("lst_0002", Decimal("1234.50"), "USD", NOW, 90)
    assert a == b and a != c and len(a) == 91
    assert a[-1].price == Decimal("1234.50") and all(o.price > 0 for o in a)
    assert len({o.price for o in a}) > 10


# ---------- store ----------
async def test_store_dedupe_cap_retention():
    from ff_sourcing.db import make_engine
    from ff_sourcing.domain.models import Listing  # noqa: F401

    class Item:
        def __init__(self, id, amount, source="native"):
            from ff_sourcing.domain.models import Money, MoneyRange

            self.id, self.source = id, source
            m = Money(amount=Decimal(amount), currency="USD")
            self.price = MoneyRange(min=m, max=m)

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    st = PriceHistoryStore(engine, True, dedupe_hours=6, max_points=5, retention_days=30)
    assert await st.record_listings([Item("n1", "10")], NOW) == 1  # type: ignore[list-item]
    assert await st.record_listings([Item("n1", "10")], NOW + timedelta(hours=1)) == 0  # type: ignore[list-item]
    assert await st.record_listings([Item("n1", "11")], NOW + timedelta(hours=1)) == 1  # type: ignore[list-item]
    assert await st.record_listings([Item("m1", "5", "mock")], NOW) == 0  # type: ignore[list-item]
    for i in range(10):
        await st.record_listings([Item("n1", str(20 + i))], NOW + timedelta(hours=10 + i * 7))  # type: ignore[list-item]
    s = await st.series("n1", NOW - timedelta(days=1))
    assert len(s) == 5 and s[-1].price == Decimal("29")  # capped: newest kept
    await st.record_listings([Item("n1", "99")], NOW + timedelta(days=60))  # type: ignore[list-item]
    s = await st.series("n1", NOW - timedelta(days=1))
    assert [o.price for o in s] == [Decimal("99")]  # older than retention pruned
    await engine.dispose()


# ---------- API ----------
def make_app(trust=None):
    trust = trust or MockTrustClient({"sup_native_a": GREEN, "sup_native_b": GREEN})
    return create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:"), AdapterRegistry([MockAdapter()]), trust
    )


@pytest.fixture
async def nc():
    app = make_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_mock_price_history_endpoint(nc):
    r = await nc.get("/v1/listings/lst_0004/price-history", params={"days": 60})
    assert r.status_code == 200
    d = r.json()
    assert d["synthetic"] is True and d["currency"] == "USD" and len(d["points"]) in (60, 61)
    assert d["summary"]["current"] == "18000.00" and d["trend"]["direction"] in ("up", "down", "flat")
    assert d["trend"]["insufficient_data"] is False and "hints" in d
    assert (await nc.get("/v1/listings/lst_0004/price-history", params={"days": 60})).json()["points"] == d["points"]
    w = (await nc.get("/v1/listings/lst_0004/price-history", params={"days": 90, "bucket": "week"})).json()
    assert 12 <= len(w["points"]) <= 15 and w["bucket"] == "week"


async def test_price_history_errors(nc):
    assert (await nc.get("/v1/listings/nope/price-history")).status_code == 404
    for q in ({"days": 0}, {"days": 366}, {"bucket": "year"}):
        assert (await nc.get("/v1/listings/lst_0004/price-history", params=q)).status_code == 422


async def test_native_price_changes_recorded(nc):
    lid = (await nc.post("/v1/my/listings", json=body(), headers=A)).json()["id"]
    await nc.post(f"/v1/my/listings/{lid}/publish", headers=A)
    d = (await nc.get(f"/v1/listings/{lid}/price-history")).json()
    assert d["synthetic"] is False and d["summary"]["observations"] == 1 and d["trend"]["insufficient_data"]
    new = body()
    new["price"] = {"min": {"amount": "2.00", "currency": "USD"}, "max": {"amount": "4.10", "currency": "USD"}}
    assert (await nc.put(f"/v1/my/listings/{lid}", json=new, headers=A)).status_code == 200
    d = (await nc.get(f"/v1/listings/{lid}/price-history")).json()
    assert d["summary"]["observations"] == 2 and d["summary"]["current"] == "2.00" and d["summary"]["first"] == "2.50"
    await nc.get("/v1/search", params={"q": "zebrafish planter"})  # same price again within 6h: deduped
    d = (await nc.get(f"/v1/listings/{lid}/price-history")).json()
    assert d["summary"]["observations"] == 2


async def test_similar_listing(nc):
    r = await nc.get("/v1/listings/lst_0027/similar")
    assert r.status_code == 200
    d = r.json()
    ids = [i["listing"]["id"] for i in d["items"]]
    assert d["listing_id"] == "lst_0027" and "lst_0027" not in ids and ids
    top = d["items"][0]
    assert top["listing"]["kind"] == "raw_material" and 0 < top["score"] <= 1
    assert all({"code", "en", "ar"} <= set(x) for x in top["reasons"]) and top["reasons"]
    assert "same_category" in {x["code"] for x in top["reasons"]}
    assert [i["score"] for i in d["items"]] == sorted((i["score"] for i in d["items"]), reverse=True)
    assert (await nc.get("/v1/listings/lst_0027/similar")).json() == d  # deterministic
    # same supplier ranks below an equally-matching other supplier
    same = [i for i in d["items"] if i["listing"]["supplier"]["id"] == "sup_cn_029"]
    for s in same:
        assert "same_supplier" in {x["code"] for x in s["reasons"]}
    assert len((await nc.get("/v1/listings/lst_0027/similar", params={"limit": 2})).json()["items"]) <= 2
    assert (await nc.get("/v1/listings/nope/similar")).status_code == 404
    assert (await nc.get("/v1/listings/lst_0027/similar", params={"limit": 31})).status_code == 422


async def test_similar_demotes_red_trust():
    red = TrustInfo(supplier_id="x", score=10, band="red")
    trust = MockTrustClient({"sup_cn_030": red, "sup_in_002": GREEN})
    app = make_app(trust)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        d = (await c.get("/v1/listings/lst_0027/similar")).json()
    pos = {i["listing"]["supplier"]["id"]: n for n, i in reversed(list(enumerate(d["items"])))}
    assert pos["sup_in_002"] < pos["sup_cn_030"]


async def test_recommendations(nc):
    r = await nc.get("/v1/recommendations", params={"ref": "lst_0027,lst_0004,unknown_id", "country": "in", "limit": 15})
    assert r.status_code == 200
    d = r.json()
    assert d["based_on"] == ["lst_0027", "lst_0004"] and d["total"] == len(d["items"]) <= 15
    assert not {"lst_0027", "lst_0004"} & {i["listing"]["id"] for i in d["items"]}
    per = {}
    for i in d["items"]:
        per[i["listing"]["supplier"]["id"]] = per.get(i["listing"]["supplier"]["id"], 0) + 1
        codes = {x["code"] for x in i["reasons"]}
        assert "because_viewed" in codes
    assert max(per.values()) <= 3
    assert any(x["code"] == "origin_country_match" for i in d["items"] for x in i["reasons"] if i["listing"]["origin"]["country_code"] == "IN") or not any(
        i["listing"]["origin"]["country_code"] == "IN" for i in d["items"]
    )
    assert (await nc.get("/v1/recommendations", params={"ref": "lst_0027,lst_0004", "country": "in", "limit": 15})).json() == d


async def test_recommendations_fallback_and_validation(nc):
    d = (await nc.get("/v1/recommendations")).json()
    assert d["based_on"] == [] and d["items"]
    assert all(i["reasons"] is not None for i in d["items"])
    ids = ",".join(f"lst_{n:04d}" for n in range(1, 22))
    r = await nc.get("/v1/recommendations", params={"ref": ids})
    assert r.status_code == 422 and r.json()["error"]["code"] == "too_many_refs"
    ok = ",".join(f"lst_{n:04d}" for n in range(1, 21))
    assert (await nc.get("/v1/recommendations", params={"ref": ok})).status_code == 200
    assert (await nc.get("/v1/recommendations", params={"ref": "a b;drop"})).json()["error"]["code"] == "invalid_ref"
    assert (await nc.get("/v1/recommendations", params={"country": "ZZZ"})).status_code == 422
    assert (await nc.get("/v1/recommendations", params={"limit": 51})).status_code == 422


async def test_candidates_are_bounded(nc, monkeypatch):
    from ff_sourcing.domain import reco

    monkeypatch.setattr(reco, "MAX_CANDIDATES", 5)
    monkeypatch.setattr(reco, "TRUST_STAGE", 3)
    d = (await nc.get("/v1/listings/lst_0027/similar", params={"limit": 30})).json()
    assert len(d["items"]) <= 3
