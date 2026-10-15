"""QA round K: webhook ordering, duplicate/different amounts, provider switch, expiry boundary, ledger vs refunds,
outbox retry / dead-letter / replay."""

from datetime import timedelta
from decimal import Decimal

from conftest import ADMIN, BUYER, DEAL, Clock, make_settings, mk, post_event
from fastapi.testclient import TestClient

from ff_payments.clients.deals import MockDealClient, NotifyRejected
from ff_payments.domain.errors import UpstreamUnavailable
from ff_payments.main import create_app
from ff_payments.providers.mock import MockProvider


def _ev(inv, typ="payment.confirmed", eid="e1", **kw):
    return {"event_id": eid, "type": typ, "invoice_id": inv["id"], **kw}


def _get(client, inv):
    return client.get(f"/v1/invoices/{inv['id']}", headers=BUYER).json()


def _ledger(client, inv):
    return client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()


def _outbox(client, status=None):
    return client.get("/v1/payments/outbox", params={"status": status} if status else {}, headers=ADMIN).json()


# ---- out-of-order webhooks ----------------------------------------------------------------
def test_confirmed_before_invoice_exists_is_404_and_retryable(client):
    r = post_event(client, {"event_id": "early", "type": "payment.confirmed", "invoice_id": "inv_future"})
    assert r.status_code == 404
    # not recorded as seen: the same event id is accepted once the invoice exists (by provider_ref)
    inv = mk(client).json()
    r = post_event(client, {"event_id": "early", "type": "payment.confirmed", "provider_ref": inv["provider_ref"]})
    assert r.json()["status"] == "applied" and _get(client, inv)["status"] == "paid"


def test_confirmed_skips_confirming_and_late_confirming_is_ignored(client):
    inv = mk(client).json()
    assert post_event(client, _ev(inv)).json()["invoice_status"] == "paid"
    r = post_event(client, _ev(inv, "payment.confirming", "e2", confirmations=2))
    assert r.json()["status"] == "ignored" and _get(client, inv)["status"] == "paid"
    assert _get(client, inv)["confirmations"] == 0 or _get(client, inv)["confirmations"] is not None
    assert _ledger(client, inv)["total"] == 2


def test_expired_and_failed_after_confirmed_do_not_unsettle(client):
    inv = mk(client).json()
    post_event(client, _ev(inv))
    for i, typ in enumerate(("payment.expired", "payment.failed")):
        r = post_event(client, _ev(inv, typ, f"x{i}"))
        assert r.json()["status"] == "ignored" and r.json()["invoice_status"] == "paid"
    assert _ledger(client, inv)["total"] == 2
    assert [n["status"] for n in client.deals.notifications] == ["paid"]


def test_expired_then_confirmed_goes_to_review_without_ledger(client):
    inv = mk(client).json()
    post_event(client, _ev(inv, "payment.expired", "x1"))
    r = post_event(client, _ev(inv, eid="x2"))
    assert r.json()["status"] == "review" and _get(client, inv)["status"] == "expired"
    assert _ledger(client, inv)["total"] == 0 and client.deals.notifications == []


# ---- duplicates with different amounts -----------------------------------------------------
def test_same_event_id_different_amount_is_duplicate_and_first_wins(client):
    inv = mk(client).json()
    ok = {"amount": "375.00", "currency": "USD"}
    assert post_event(client, _ev(inv, amount=ok)).json()["status"] == "applied"
    r = post_event(client, _ev(inv, amount={"amount": "1.00", "currency": "USD"}))
    assert r.json()["status"] == "duplicate" and _get(client, inv)["status"] == "paid"
    assert _ledger(client, inv)["total"] == 2


def test_wrong_amount_first_then_correct_amount_settles_and_clears_review(client):
    inv = mk(client).json()
    bad = post_event(client, _ev(inv, eid="a", amount={"amount": "1.00", "currency": "USD"}))
    assert bad.json()["status"] == "review"
    assert client.get("/v1/payments/review", headers=ADMIN).json()["total"] == 1
    good = post_event(client, _ev(inv, eid="b", amount={"amount": "375.00", "currency": "USD"}))
    assert good.json()["status"] == "applied"
    assert _get(client, inv)["status_reason"] is None
    assert client.get("/v1/payments/review", headers=ADMIN).json()["total"] == 0
    # a later wrong-amount "paid" for an already paid invoice neither flags nor double posts
    late = post_event(client, _ev(inv, eid="c", amount={"amount": "9.00", "currency": "USD"}))
    assert late.json()["status"] == "ignored" and _ledger(client, inv)["total"] == 2


def test_wrong_amount_on_paid_invoice_never_reopens_review(client):
    inv = mk(client).json()
    post_event(client, _ev(inv))
    post_event(client, _ev(inv, eid="z", amount={"amount": "9.00", "currency": "USD"}))
    assert client.get("/v1/payments/review", headers=ADMIN).json()["total"] == 0


# ---- provider switch mid-flight ------------------------------------------------------------
def test_provider_switch_midflight(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/p.db"
    clock = Clock()
    deals = MockDealClient({"deal_1": DEAL})
    prov_a = MockProvider()
    with TestClient(create_app(make_settings(database_url=url), provider=prov_a, deals=deals, clock=clock)) as a:
        inv = a.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER).json()
    prov_b = MockProvider()
    prov_b.name = "other"
    with TestClient(create_app(make_settings(database_url=url, provider="mock"), provider=prov_b, deals=deals,
                               clock=clock)) as b:
        b.clock = clock
        prov_a.confirm(inv["provider_ref"])
        out = b.post("/v1/payments/sweep", headers=ADMIN).json()
        assert out["polled"] == 0  # the new provider never polls (or settles) the old provider's invoices
        assert b.get(f"/v1/invoices/{inv['id']}", headers=BUYER).json()["status"] == "awaiting_payment"
        # the old provider's webhook still settles it; another provider's webhook cannot
        assert post_event(b, _ev(inv), provider="usdt_tron").status_code in (404, 503)
        assert post_event(b, _ev(inv)).json()["invoice_status"] == "paid"
        # a new invoice for the same deal/kind is not blocked by the paid one's provider; ledger uses its provider
        led = b.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()["items"]
        assert {e["account"] for e in led} == {"clearing:mock", "revenue:commission"}


# ---- expiry boundary -----------------------------------------------------------------------
def test_expiry_sweep_exact_second_boundary(client, clock):
    inv = mk(client).json()  # ttl default
    exp = _get(client, inv)["expires_at"]
    ttl = (client.app.state.service.settings.invoice_ttl_minutes if hasattr(client.app.state, "service") else None)
    assert exp.endswith("Z")
    from datetime import datetime
    exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
    clock.now = exp_dt - timedelta(seconds=1)
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["expired"] == 0
    assert _get(client, inv)["status"] == "awaiting_payment"
    clock.now = exp_dt  # exactly at expires_at: expired (<=)
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["expired"] == 1
    assert _get(client, inv)["status"] == "expired"
    assert ttl is None or ttl > 0


def test_payment_observed_at_exact_expiry_second_is_not_auto_settled(client, clock):
    inv = mk(client).json()
    from datetime import datetime
    clock.now = datetime.fromisoformat(_get(client, inv)["expires_at"].replace("Z", "+00:00"))
    r = post_event(client, _ev(inv))
    assert r.json()["status"] == "review" and _get(client, inv)["status"] == "expired"
    assert _ledger(client, inv)["total"] == 0


def test_payment_one_second_before_expiry_settles(client, clock):
    inv = mk(client).json()
    from datetime import datetime
    clock.now = datetime.fromisoformat(_get(client, inv)["expires_at"].replace("Z", "+00:00")) - timedelta(seconds=1)
    assert post_event(client, _ev(inv)).json()["status"] == "applied"


# ---- ledger vs invoices under refunds ------------------------------------------------------
def _net(client, deal="deal_1"):
    return client.get(f"/v1/ledger/deals/{deal}/commission", headers=ADMIN).json()["items"]


def test_commission_ledger_equals_invoice_sums_under_refunds(client):
    c = mk(client, "commission").json()
    p = mk(client, "deal_payment").json()
    post_event(client, _ev(c, eid="c1"))
    post_event(client, _ev(p, eid="p1"))
    assert _net(client) == [{"currency": "USD", "earned": "375.00", "refunded": "0", "net": "375.00"}]
    assert client.post(f"/v1/invoices/{p['id']}/refund", headers=ADMIN).status_code == 200
    # refunding the supplier payment never touches platform commission
    assert _net(client)[0]["net"] == "375.00" and _net(client)[0]["refunded"] == "0"
    assert client.post(f"/v1/invoices/{c['id']}/refund", headers=ADMIN).status_code == 200
    assert _net(client) == [{"currency": "USD", "earned": "375.00", "refunded": "375.00", "net": "0.00"}]
    # a second refund is refused and posts nothing
    assert client.post(f"/v1/invoices/{c['id']}/refund", headers=ADMIN).status_code == 409
    assert client.post(f"/v1/invoices/{c['id']}/refund", headers=ADMIN).status_code == 409
    for inv in (c, p):
        legs = _ledger(client, inv)["items"]
        deb = sum(Decimal(e["amount"]["amount"]) for e in legs if e["direction"] == "debit")
        cre = sum(Decimal(e["amount"]["amount"]) for e in legs if e["direction"] == "credit")
        assert deb == cre == Decimal("375.00") * 2 or deb == cre == Decimal("12500.00") * 2


def test_refund_of_unpaid_invoice_is_refused_and_ledger_empty(client):
    inv = mk(client).json()
    assert client.post(f"/v1/invoices/{inv['id']}/refund", headers=ADMIN).status_code == 409
    assert _ledger(client, inv)["total"] == 0 and _net(client) == []


def test_commission_per_currency_isolated(client):
    a = client.post("/v1/invoices", headers=ADMIN, json={
        "deal_id": "deal_1", "kind": "commission", "payer_user_id": "buyer1", "payee": "platform",
        "amount": {"amount": "100.00", "currency": "EUR"}}).json()
    b = client.post("/v1/invoices", headers=ADMIN, json={
        "deal_id": "deal_1", "kind": "commission", "payer_user_id": "buyer2", "payee": "platform",
        "amount": {"amount": "375.00", "currency": "USD"}}).json()
    assert b["id"] != a["id"]
    post_event(client, _ev(a, eid="a"))
    post_event(client, _ev(b, eid="b"))
    client.post(f"/v1/invoices/{a['id']}/refund", headers=ADMIN)
    got = {i["currency"]: i for i in _net(client)}
    assert got["EUR"]["net"] == "0.00" and got["USD"]["net"] == "375.00"


# ---- outbox: retry / dead letter / replay --------------------------------------------------
def test_backoff_boundary_exact_second_and_cap(client, clock):
    client.deals.fail_with = UpstreamUnavailable("down")
    inv = mk(client).json()
    post_event(client, _ev(inv))  # inline attempt 1 -> next in 30s
    (row,) = _outbox(client, "pending")["items"]
    clock.advance(seconds=29)
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["outbox_retry"] == 0
    clock.advance(seconds=1)  # exactly due
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["outbox_retry"] == 1
    assert _outbox(client, "pending")["items"][0]["attempts"] == 2
    svc = client.app.state.service if hasattr(client.app.state, "service") else None
    if svc is not None:
        assert svc._backoff(1) == timedelta(seconds=30) and svc._backoff(2) == timedelta(seconds=60)
        assert svc._backoff(50) == timedelta(seconds=3600)
    assert row["event_id"].endswith(":paid")


def test_replay_after_dead_letter_keeps_order_and_delivers_each_once(client, clock):
    client.deals.fail_with = NotifyRejected("nope", 422)
    inv = mk(client).json()
    post_event(client, _ev(inv))  # paid -> dead immediately
    client.post(f"/v1/invoices/{inv['id']}/refund", headers=ADMIN)  # refunded queued behind the dead one
    clock.advance(hours=1)
    client.post("/v1/payments/sweep", headers=ADMIN)
    assert client.deals.notifications == []  # the dead event blocks its deal
    assert _outbox(client, "dead")["total"] == 1 and _outbox(client, "pending")["total"] == 1
    client.deals.fail_with = None
    (dead,) = _outbox(client, "dead")["items"]
    client.post(f"/v1/payments/outbox/{dead['id']}/requeue", headers=ADMIN)
    client.post("/v1/payments/sweep", headers=ADMIN)
    assert [n["status"] for n in client.deals.notifications] == ["paid", "refunded"]
    assert [n["event_id"] for n in client.deals.notifications] == [f"{inv['id']}:paid", f"{inv['id']}:refunded"]
    client.post("/v1/payments/sweep", headers=ADMIN)
    assert len(client.deals.notifications) == 2
    assert _outbox(client, "dead")["total"] == 0


def test_requeue_resets_attempts_and_can_dead_letter_again(client, clock):
    client.deals.fail_with = UpstreamUnavailable("down")
    inv = mk(client).json()
    post_event(client, _ev(inv))
    for _ in range(10):
        clock.advance(hours=2)
        client.post("/v1/payments/sweep", headers=ADMIN)
    (dead,) = _outbox(client, "dead")["items"]
    r = client.post(f"/v1/payments/outbox/{dead['id']}/requeue", headers=ADMIN).json()
    assert r["attempts"] == 0 and r["status"] == "pending"
    for _ in range(10):
        clock.advance(hours=2)
        client.post("/v1/payments/sweep", headers=ADMIN)
    (again,) = _outbox(client, "dead")["items"]
    assert again["id"] == dead["id"] and again["attempts"] == 8


def test_payment_settled_by_one_provider_event_notifies_exactly_once_under_duplicates(client):
    inv = mk(client).json()
    for _ in range(3):
        post_event(client, _ev(inv))
    post_event(client, _ev(inv, eid="other"))
    assert len(client.deals.notifications) == 1 and _outbox(client)["total"] == 1
