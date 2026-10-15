"""QA2: races on a file-backed sqlite DB (real write contention, separate service instances = separate pools)."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from ff_rfq.clients.sourcing import MockSourcingClient
from ff_rfq.config import Settings
from ff_rfq.db import DealRow, OfferRow, make_engine
from ff_rfq.domain.commission import compute_commission
from ff_rfq.domain.enums import ListingKind
from ff_rfq.domain.errors import DomainError
from ff_rfq.schemas import OfferCreate, RequestCreate
from ff_rfq.service import RfqService

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _req(**over):
    return RequestCreate(**{"kind": "product", "title": "LED panel lights", "quantity": "1000", "unit": "piece",
                            "destination": {"country_code": "IQ", "city": "Baghdad"}, **over})


def _offer(amount="12.50"):
    return OfferCreate(price={"amount": amount, "currency": "USD"}, supplier_name="Acme")


@pytest.fixture
async def svcs(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'rfq.db'}"
    settings = Settings(database_url=url, sourcing_client="mock")
    engines, services = [], []
    for _ in range(3):  # three "processes"
        e = make_engine(url)
        engines.append(e)
        services.append(RfqService(e, settings, MockSourcingClient(), lambda: NOW))
    await services[0].create_tables()
    yield services
    for e in engines:
        await e.dispose()


async def _count(svc, model):
    async with svc._sessions() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


async def _gather(coros):
    return await asyncio.gather(*coros, return_exceptions=True)


def _split(results):
    ok = [r for r in results if not isinstance(r, BaseException)]
    bad = [r for r in results if isinstance(r, BaseException)]
    return ok, bad


async def test_double_accept_same_offer_one_deal(svcs):
    r = await svcs[0].create_request("buyer1", _req())
    o = await svcs[0].create_offer("supA", r["id"], _offer())
    res = await _gather([svcs[i % 3].accept_offer("buyer1", o["id"]) for i in range(6)])
    ok, bad = _split(res)
    assert len(ok) == 1, res
    assert all(isinstance(b, DomainError) for b in bad), bad
    assert await _count(svcs[0], DealRow) == 1


async def test_double_award_two_offers_one_deal(svcs):
    r = await svcs[0].create_request("buyer1", _req())
    o1 = await svcs[0].create_offer("supA", r["id"], _offer("10"))
    o2 = await svcs[0].create_offer("supB", r["id"], _offer("11"))
    res = await _gather([svcs[0].accept_offer("buyer1", o1["id"]), svcs[1].accept_offer("buyer1", o2["id"]),
                         svcs[2].accept_offer("buyer1", o1["id"]), svcs[1].accept_offer("buyer1", o1["id"])])
    ok, bad = _split(res)
    assert len(ok) == 1, res
    assert all(isinstance(b, DomainError) for b in bad), bad
    assert await _count(svcs[0], DealRow) == 1
    async with svcs[0]._sessions() as s:
        statuses = sorted((await s.execute(select(OfferRow.status))).scalars())
    assert statuses.count("accepted") == 1


async def test_accept_vs_withdraw_race_is_consistent(svcs):
    r = await svcs[0].create_request("buyer1", _req())
    o = await svcs[0].create_offer("supA", r["id"], _offer())
    res = await _gather([svcs[0].accept_offer("buyer1", o["id"]), svcs[1].withdraw_offer("supA", o["id"])])
    ok, bad = _split(res)
    assert len(ok) == 1 and all(isinstance(b, DomainError) for b in bad), res
    deals = await _count(svcs[0], DealRow)
    async with svcs[0]._sessions() as s:
        st = (await s.execute(select(OfferRow.status))).scalar_one()
    assert (deals, st) in {(1, "accepted"), (0, "withdrawn")}


async def test_duplicate_offers_same_supplier_respect_cap(svcs):
    r = await svcs[0].create_request("buyer1", _req())
    res = await _gather([svcs[i % 3].create_offer("supA", r["id"], _offer(str(10 + i))) for i in range(12)])
    ok, bad = _split(res)
    assert len(ok) == 5, res  # MAX_ACTIVE_OFFERS_PER_SUPPLIER
    assert all(isinstance(b, DomainError) for b in bad), bad
    assert await _count(svcs[0], OfferRow) == 5


@pytest.mark.parametrize("cur,amount,qty,kind,expect", [
    ("USD", "0.01", "1", ListingKind.PRODUCT, ("25.00", True)),          # min-fee floor
    ("USD", "1000", "1", ListingKind.PRODUCT, ("30.00", False)),         # 3%
    ("USD", "833.33", "1", ListingKind.PRODUCT, ("25.00", False)),       # 24.9999 -> 25.00 half-up
    ("USD", "0.005", "1", ListingKind.PRODUCT, ("25.00", True)),
    ("IQD", "1", "1", ListingKind.PRODUCT, ("32894.74", True)),          # ceil(25/0.00076)
    ("USD", "10000.50", "1", ListingKind.PRODUCTION_LINE, ("400.02", False)),  # 400.02 exact
    ("USD", "1666.65", "1", ListingKind.RAW_MATERIAL, ("33.33", False)),
])
def test_commission_precision_lock(cur, amount, qty, kind, expect):
    sub = (Decimal(amount) * Decimal(qty)).quantize(Decimal("0.01"))
    fee = compute_commission(sub, cur, kind)
    assert (format(fee.amount, "f"), fee.min_fee_applied) == expect


async def test_deal_precision_fractional_qty_exact(svcs):
    r = await svcs[0].create_request("buyer1", _req(quantity="333.333", unit="kg"))
    o = await svcs[0].create_offer("supA", r["id"], _offer("0.3"))
    d = await svcs[0].accept_offer("buyer1", o["id"])
    assert d["subtotal"]["amount"] == "100.00"  # 99.9999 -> 100.00
    assert d["commission"]["amount"]["amount"] == "25.00"
