"""QA review of the USDT-TRC20 skeleton: offline, canned TronGrid-like payloads (wire shape UNVERIFIED)."""

from decimal import ROUND_HALF_UP, Decimal

import httpx
import pytest
from conftest import ADMIN, BUYER, DEAL, Clock, make_settings
from fastapi.testclient import TestClient

from ff_payments.clients.deals import MockDealClient
from ff_payments.domain.commission import compute_commission
from ff_payments.domain.enums import Direction, ListingKind
from ff_payments.domain.ledger import (
    LedgerImbalance,
    Leg,
    check_balanced,
    payment_legs,
    refund_legs,
)
from ff_payments.main import create_app
from ff_payments.providers.base import TrackedInvoice
from ff_payments.providers.usdt_tron import (
    ExplorerClient,
    UsdtTronProvider,
    is_valid_tron_address,
    parse_micro,
)

ADDR = "TNPeeaaFB7K9cmo4uQpcU32zGK8G1NYqeL"
CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
T0 = int(Clock().now.timestamp() * 1000)


class Chain:
    def __init__(self):
        self.txs: list[dict] = []
        self.latest = 1000

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/blocks/latest"):
            return httpx.Response(200, json={"data": [{"block_number": self.latest}]})
        return httpx.Response(200, json={"data": self.txs})


def prov(chain, **kw):
    ex = ExplorerClient("https://explorer.invalid", transport=httpx.MockTransport(chain.handler))
    return UsdtTronProvider(address=ADDR, contract=CONTRACT, explorer=ex, **kw)


def tx(micro, block=990, tid="tx1", ts=T0 + 1000, **over):
    d = {"transaction_id": tid, "value": str(micro), "block_number": block, "block_timestamp": ts,
         "to": ADDR, "token_info": {"address": CONTRACT, "decimals": 6, "symbol": "USDT"}}
    d.update(over)
    return d


def tracked(pay="375.000123"):
    return TrackedInvoice("ref", "memo", ADDR, Decimal(pay), T0)


# ---- address validation ------------------------------------------------------------------
@pytest.mark.parametrize("a", [ADDR, CONTRACT, "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7"])
def test_valid_addresses(a):
    assert is_valid_tron_address(a)


@pytest.mark.parametrize("a", [
    "", None, 123, ADDR[:-1], ADDR + "x", "X" + ADDR[1:], "T" + ADDR[1:-1] + ("a" if ADDR[-1] != "a" else "b"),
    ADDR[:5] + ("1" if ADDR[5] != "1" else "2") + ADDR[6:],  # checksum catches a one-char typo
    "TPublicReceivingAddressForTests000000",  # '0' not in base58 alphabet
    "0x" + "a" * 32,  # EVM style
])
def test_invalid_addresses(a):
    assert not is_valid_tron_address(a)


def test_create_rejects_bad_configured_address():
    p = UsdtTronProvider(address="T" + "1" * 33, contract=CONTRACT, explorer=ExplorerClient("https://x.invalid"))
    with TestClient(create_app(make_settings(provider="off"), provider=p,
                               deals=MockDealClient({"deal_1": DEAL}), clock=Clock())) as c:
        r = c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER)
        assert r.status_code == 503 and r.json()["error"]["code"] == "invalid_address"


# ---- amount precision --------------------------------------------------------------------
def test_parse_micro_is_exact_and_strict():
    assert parse_micro("375000123") == Decimal("375.000123")
    assert parse_micro(1) == Decimal("0.000001")
    assert parse_micro("9007199254740993") == Decimal("9007199254.740993")  # beyond float precision
    for bad in ("1.5", "1e6", "-5", " 5", "", "٣", 1.5, None, True, [1]):
        assert parse_micro(bad) is None


# ---- matching / amounts ------------------------------------------------------------------
async def poll(chain, inv=None, **kw):
    return await prov(chain, **kw).poll(inv or tracked())


@pytest.mark.anyio
async def test_exact_match_confirmation_depth_boundaries():
    ch = Chain()
    ch.txs = [tx(375_000_123, block=981)]
    ch.latest = 1000  # 1000-981+1 = 20
    o = await poll(ch)
    assert (o.status, o.confirmations, o.tx_ref) == ("paid", 20, "tx1")
    ch.latest = 999
    o = await poll(ch)
    assert (o.status, o.confirmations) == ("confirming", 19)
    ch.latest = 900  # node lagging behind: never negative
    assert (await poll(ch)).confirmations == 0


@pytest.mark.anyio
async def test_underpay_overpay_wrong_token_and_old_tx_never_match():
    ch = Chain()
    ch.txs = [tx(375_000_122, tid="under"), tx(375_000_124, tid="over"), tx(400_000_000, tid="big"),
              tx(375_000_123, tid="othertok", token_info={"address": "T" + "1" * 33}),
              tx(375_000_123, tid="notoken", token_info=None),
              tx(375_000_123, tid="elsewhere", to="T" + "2" * 33),
              tx(375_000_123, tid="old", ts=T0 - 1),
              tx("375000123.0", tid="frac"), tx(375.000123, tid="float"), tx(375_000_123, tid="")]
    assert await poll(ch) is None


@pytest.mark.anyio
async def test_malformed_payload_entries_are_skipped():
    ch = Chain()
    ch.txs = ["junk", {}, {"value": "x"}, tx(375_000_123, tid="ok")]
    assert (await poll(ch)).tx_ref == "ok"


@pytest.mark.anyio
async def test_duplicate_same_amount_picks_earliest_block_and_unmined_is_zero_conf():
    ch = Chain()
    ch.txs = [tx(375_000_123, block=995, tid="b"), tx(375_000_123, block=990, tid="a")]
    assert (await poll(ch)).tx_ref == "a"
    ch.txs = [tx(375_000_123, block=None, tid="mempool")]
    o = await poll(ch)
    assert (o.status, o.confirmations) == ("confirming", 0)  # no block => 0 confirmations, never paid


@pytest.mark.anyio
async def test_min_confirmations_floor_is_one():
    ch = Chain()
    ch.txs = [tx(375_000_123, block=None)]
    assert (await poll(ch, min_confirmations=0)).status == "confirming"


# ---- service level -----------------------------------------------------------------------
def boot(chain, clock):
    app = create_app(make_settings(provider="off"), provider=prov(chain), clock=clock,
                     deals=MockDealClient({"deal_1": DEAL}))
    return TestClient(app)


def inv(c, kind="commission"):
    return c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": kind}, headers=BUYER).json()


def micro_of(i):
    return int(Decimal(i["pay_amount"]["amount"]) * 1_000_000)


def sweep(c):
    return c.post("/v1/payments/sweep", headers=ADMIN).json()


def status(c, i):
    return c.get(f"/v1/invoices/{i['id']}", headers=BUYER).json()


def test_reorg_confirming_goes_back_then_settles_and_never_expires_while_confirming():
    ch, clock = Chain(), Clock()
    with boot(ch, clock) as c:
        i = inv(c)
        ch.txs, ch.latest = [tx(micro_of(i), block=995, ts=T0 + 5)], 1000
        assert sweep(c)["updated"] == 1 and status(c, i)["status"] == "confirming"
        clock.advance(hours=5)  # confirming never expires
        assert status(c, i)["status"] == "confirming"
        ch.txs = []  # reorg: transfer vanished
        assert sweep(c)["updated"] == 1
        s = status(c, i)
        assert s["status"] == "awaiting_payment" and s["tx_ref"] is None and s["confirmations"] == 0
        clock.advance(minutes=29)  # grace window after a reorg
        assert status(c, i)["status"] == "awaiting_payment"
        ch.txs, ch.latest = [tx(micro_of(i), block=1100, tid="tx_new", ts=T0 + 9)], 1200
        assert sweep(c)["updated"] == 1 and status(c, i)["status"] == "paid"
        assert status(c, i)["tx_ref"] == "tx_new"
        assert c.get("/v1/ledger", params={"invoice_id": i["id"]}, headers=ADMIN).json()["total"] == 2


def test_sweep_is_idempotent_one_ledger_group_and_one_outbox_event():
    ch, clock = Chain(), Clock()
    with boot(ch, clock) as c:
        i = inv(c)
        ch.txs, ch.latest = [tx(micro_of(i), block=900)], 1000
        sweep(c)
        for _ in range(3):
            assert sweep(c)["updated"] == 0
        led = c.get("/v1/ledger", params={"invoice_id": i["id"]}, headers=ADMIN).json()
        assert led["total"] == 2
        ob = c.get("/v1/payments/outbox", headers=ADMIN).json()
        assert ob["total"] == 1


def test_paid_invoice_ignores_vanishing_tx():
    ch, clock = Chain(), Clock()
    with boot(ch, clock) as c:
        i = inv(c)
        ch.txs, ch.latest = [tx(micro_of(i), block=900)], 1000
        sweep(c)
        ch.txs = []
        sweep(c)
        assert status(c, i)["status"] == "paid"  # paid is final; clawback is a manual/refund matter


def test_same_tx_cannot_settle_two_invoices():
    ch, clock = Chain(), Clock()
    with boot(ch, clock) as c:
        a, b = inv(c, "commission"), inv(c, "deal_payment")
        # both invoices (forced to the same amount) would see the same transfer
        ch.txs, ch.latest = [tx(micro_of(a), block=900, tid="same")], 1000
        sweep(c)
        assert status(c, a)["status"] == "paid"
        ch.txs = [tx(micro_of(b), block=900, tid="same")]
        sweep(c)
        assert status(c, b)["status"] == "awaiting_payment"


def test_expiry_vs_late_payment():
    ch, clock = Chain(), Clock()
    with boot(ch, clock) as c:
        i, j = inv(c), inv(c, "deal_payment")
        clock.advance(minutes=61)  # both past TTL, nothing read yet
        # payment mined before expiry but only seen now: the sweep polls BEFORE it expires => paid
        ch.txs, ch.latest = [tx(micro_of(i), block=900, ts=T0 + 60_000)], 1000
        out = sweep(c)
        assert out["updated"] == 1 and out["expired"] == 1
        assert status(c, i)["status"] == "paid" and status(c, j)["status"] == "expired"
        # a transfer for the already-expired invoice arriving later is NOT auto-settled
        ch.txs = [tx(micro_of(j), block=1100, tid="late", ts=T0 + 7_200_000)]
        ch.latest = 1200
        assert sweep(c)["updated"] == 0
        assert status(c, j)["status"] == "expired"
        assert c.get("/v1/ledger", params={"invoice_id": j["id"]}, headers=ADMIN).json()["total"] == 0


def test_explorer_outage_keeps_confirming_invoice():
    ch2, clock2 = Chain(), Clock()
    p = prov(ch2)
    app = create_app(make_settings(provider="off"), provider=p, clock=clock2, deals=MockDealClient({"deal_1": DEAL}))
    with TestClient(app) as c:
        i = inv(c)
        ch2.txs, ch2.latest = [tx(micro_of(i), block=995, ts=T0 + 5)], 1000
        sweep(c)
        p.explorer._c = httpx.AsyncClient(base_url="https://e.invalid", transport=httpx.MockTransport(
            lambda r: httpx.Response(500)))
        assert sweep(c)["updated"] == 0 and status(c, i)["status"] == "confirming"  # outage != reorg


# ---- ledger / commission invariants ------------------------------------------------------
def test_ledger_groups_balance_and_refund_reverses():
    legs = payment_legs(provider="usdt_tron", payee="sup1", kind="deal_payment", amount=Decimal("12500.00"),
                        currency="USD")
    check_balanced(legs)
    check_balanced(legs + refund_legs(legs))
    assert sum(x.amount for x in legs if x.direction == Direction.DEBIT) == \
        sum(x.amount for x in legs if x.direction == Direction.CREDIT)
    with pytest.raises(LedgerImbalance):
        check_balanced([Leg("a", Direction.DEBIT, Decimal("1.00"), "USD"),
                        Leg("b", Direction.CREDIT, Decimal("0.99"), "USD")])
    with pytest.raises(LedgerImbalance):  # balanced only by mixing currencies: rejected
        check_balanced([Leg("a", Direction.DEBIT, Decimal("1"), "USD"), Leg("b", Direction.CREDIT, Decimal("1"), "EUR")])
    with pytest.raises(LedgerImbalance):
        check_balanced([])


def test_ledger_sums_per_invoice_in_db_after_pay_and_refund():
    ch, clock = Chain(), Clock()
    with boot(ch, clock) as c:
        i = inv(c)
        ch.txs, ch.latest = [tx(micro_of(i), block=900)], 1000
        sweep(c)
        assert c.post(f"/v1/invoices/{i['id']}/refund", headers=ADMIN).status_code == 200
        rows = c.get("/v1/ledger", params={"invoice_id": i["id"]}, headers=ADMIN).json()
        items = rows.get("items") or rows.get("entries")
        d = sum(Decimal(e["amount"]["amount"] if isinstance(e["amount"], dict) else e["amount"])
                for e in items if e["direction"] == "debit")
        k = sum(Decimal(e["amount"]["amount"] if isinstance(e["amount"], dict) else e["amount"])
                for e in items if e["direction"] == "credit")
        assert len(items) == 4 and d == k == Decimal("750.00")


@pytest.mark.parametrize("sub,exp", [("0.00", "25.00"), ("1000.00", "30.00"), ("1000.17", "30.01"),
                                     ("1000.50", "30.02"), ("12500.00", "375.00"), ("333.33", "25.00")])
def test_commission_half_up_and_minimum(sub, exp):
    got = compute_commission(Decimal(sub), "USD", ListingKind.PRODUCT).amount
    assert got == Decimal(exp)
    if got != Decimal("25.00"):
        assert got == (Decimal(sub) * Decimal("0.03")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
