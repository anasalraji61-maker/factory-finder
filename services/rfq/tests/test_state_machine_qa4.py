"""QA4: exhaustive state-machine matrix + deal-lifecycle races (file-backed sqlite, separate pools)."""

import asyncio
import itertools
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from ff_rfq.clients.sourcing import MockSourcingClient
from ff_rfq.config import Settings
from ff_rfq.db import DealEventRow, DealRow, make_engine
from ff_rfq.deals import DealService
from ff_rfq.domain.enums import DealStatus as D
from ff_rfq.domain.enums import OfferStatus as O
from ff_rfq.domain.enums import RequestStatus as R
from ff_rfq.domain.errors import DomainError, InvalidTransition
from ff_rfq.domain.state import (
    DEAL_ACTIONS,
    OFFER_ACTIONS,
    REQUEST_ACTIONS,
    deal_transition,
    offer_transition,
    request_transition,
)
from ff_rfq.schemas import OfferCreate, PaymentStatusCallback, RequestCreate
from ff_rfq.service import RfqService

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(("enum", "table", "fn"), [
    (R, REQUEST_ACTIONS, request_transition), (O, OFFER_ACTIONS, offer_transition),
    (D, DEAL_ACTIONS, deal_transition)])
def test_every_transition_pair_legal_or_rejected(enum, table, fn):
    for state, action in itertools.product(enum, table):
        src, target = table[action]
        if state in src:
            assert fn(state, action) == target
        else:
            with pytest.raises(InvalidTransition) as ei:
                fn(state, action, "x")
            assert action not in ei.value.details.get("allowed", []) or state not in src


@pytest.mark.parametrize("table", [REQUEST_ACTIONS, OFFER_ACTIONS, DEAL_ACTIONS])
def test_terminal_states_have_no_exit(table):
    terminals = {"awarded", "closed", "expired", "accepted", "rejected", "withdrawn", "completed", "refunded", "disputed"}
    for src, _ in table.values():
        assert not ({s.value for s in src} & terminals)


@pytest.fixture
async def svcs(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'rfq.db'}"
    settings = Settings(database_url=url, sourcing_client="mock")
    engines, rfq, deals = [], [], []
    for _ in range(3):
        e = make_engine(url)
        engines.append(e)
        s = RfqService(e, settings, MockSourcingClient(), lambda: NOW)
        rfq.append(s)
        deals.append(DealService(e, lambda: NOW))
    await rfq[0].create_tables()
    yield rfq, deals
    for e in engines:
        await e.dispose()


async def _paid_deal(rfq, deals):
    r = await rfq[0].create_request("buyer1", RequestCreate(kind="product", title="LED lights", quantity="10", unit="piece"))
    o = await rfq[0].create_offer("supA", r["id"], OfferCreate(price={"amount": "10", "currency": "USD"}, supplier_name="A"))
    d = await rfq[0].accept_offer("buyer1", o["id"])
    await deals[0].apply_payment_status(d["id"], PaymentStatusCallback(
        invoice_id="i1", kind="deal_payment", status="paid", amount=d["subtotal"],
        event_id="e0", other_open_kinds=[]))
    return d


async def _events(rfq, deal_id, action):
    async with rfq[0]._sessions() as s:
        return (await s.execute(select(func.count()).select_from(DealEventRow).where(
            DealEventRow.deal_id == deal_id, DealEventRow.action == action))).scalar_one()


async def test_concurrent_start_fulfilment_is_idempotent_single_event(svcs):
    rfq, deals = svcs
    d = await _paid_deal(rfq, deals)
    res = await asyncio.gather(*[deals[i % 3].start_fulfilment("supA", None, d["id"]) for i in range(6)],
                               return_exceptions=True)
    assert not [r for r in res if isinstance(r, BaseException)], res
    assert await _events(rfq, d["id"], "fulfilment_started") == 1


async def test_concurrent_confirm_receipt_single_completion(svcs):
    rfq, deals = svcs
    d = await _paid_deal(rfq, deals)
    await deals[0].start_fulfilment("supA", None, d["id"])
    res = await asyncio.gather(*[deals[i % 3].confirm_receipt("buyer1", d["id"]) for i in range(6)],
                               return_exceptions=True)
    assert not [r for r in res if isinstance(r, BaseException)], res
    assert await _events(rfq, d["id"], "receipt_confirmed") == 1
    again = await deals[1].confirm_receipt("buyer1", d["id"])
    assert again["status"] == "completed"


async def test_concurrent_duplicate_payment_event_single_effect(svcs):
    rfq, deals = svcs
    r = await rfq[0].create_request("buyer1", RequestCreate(kind="product", title="LED lights", quantity="10", unit="piece"))
    o = await rfq[0].create_offer("supA", r["id"], OfferCreate(price={"amount": "10", "currency": "USD"}, supplier_name="A"))
    d = await rfq[0].accept_offer("buyer1", o["id"])
    body = PaymentStatusCallback(invoice_id="i1", kind="deal_payment", status="paid",
                                 amount=d["subtotal"], event_id="same", other_open_kinds=[])
    res = await asyncio.gather(*[deals[i % 3].apply_payment_status(d["id"], body) for i in range(6)],
                               return_exceptions=True)
    assert not [x for x in res if isinstance(x, BaseException)], res
    assert sorted(x["outcome"] for x in res).count("applied") == 1
    async with rfq[0]._sessions() as s:
        assert (await s.execute(select(func.count()).select_from(DealEventRow))).scalar_one() == 1
        assert (await s.execute(select(DealRow.status))).scalar_one() == "paid"


async def test_start_fulfilment_vs_refund_race_consistent(svcs):
    rfq, deals = svcs
    d = await _paid_deal(rfq, deals)
    refund = PaymentStatusCallback(invoice_id="i1", kind="deal_payment", status="refunded",
                                   amount=d["subtotal"], event_id="r1")
    res = await asyncio.gather(deals[0].start_fulfilment("supA", None, d["id"]),
                               deals[1].apply_payment_status(d["id"], refund), return_exceptions=True)
    assert all(not isinstance(x, BaseException) or isinstance(x, DomainError) for x in res), res
    async with rfq[0]._sessions() as s:
        st = (await s.execute(select(DealRow.status))).scalar_one()
        seqs = sorted((await s.execute(select(DealEventRow.seq))).scalars())
    assert st in {"refunded", "disputed"}
    assert seqs == list(range(1, len(seqs) + 1))  # gap-free, unique


async def test_offer_and_request_replays_rejected_never_double_applied(svcs):
    rfq, _ = svcs
    r = await rfq[0].create_request("buyer1", RequestCreate(kind="product", title="LED lights", quantity="10", unit="piece"))
    o = await rfq[0].create_offer("supA", r["id"], OfferCreate(price={"amount": "10", "currency": "USD"}, supplier_name="A"))
    await rfq[0].withdraw_offer("supA", o["id"])
    for fn, args in ((rfq[1].withdraw_offer, ("supA", o["id"])), (rfq[1].accept_offer, ("buyer1", o["id"])),
                     (rfq[1].reject_offer, ("buyer1", o["id"]))):
        with pytest.raises(InvalidTransition):
            await fn(*args)
    await rfq[0].close_request("buyer1", r["id"])
    with pytest.raises(InvalidTransition):
        await rfq[2].close_request("buyer1", r["id"])
