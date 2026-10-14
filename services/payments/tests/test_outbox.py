"""rfq settlement callback: transactional outbox, retries with backoff, dead letters, ordering, http client."""

import httpx
import pytest
from conftest import ADMIN, BUYER, DEAL, Clock, make_settings, mk, post_event
from fastapi.testclient import TestClient

from ff_payments.clients.deals import HttpDealClient, MockDealClient, NotifyRejected
from ff_payments.domain.errors import UpstreamUnavailable
from ff_payments.main import create_app
from ff_payments.providers.mock import MockProvider


def pay_via_sweep(client, inv):
    client.provider.confirm(inv["provider_ref"])
    return client.post("/v1/payments/sweep", headers=ADMIN).json()


def outbox(client, status=None):
    return client.get("/v1/payments/outbox", params={"status": status} if status else {}, headers=ADMIN).json()


def test_sweep_settles_and_notifies_rfq_once(client):
    inv = mk(client, "deal_payment").json()
    assert client.deals.notifications == []
    out = pay_via_sweep(client, inv)
    assert out["updated"] == 1 and out["outbox_delivered"] == 1
    (n,) = client.deals.notifications
    assert n == {"deal_id": "deal_1", "invoice_id": inv["id"], "kind": "deal_payment", "status": "paid",
                 "amount": {"amount": "12500.00", "currency": "USD"}, "event_id": f"{inv['id']}:paid",
                 "other_open_kinds": []}
    client.post("/v1/payments/sweep", headers=ADMIN)  # nothing new
    assert len(client.deals.notifications) == 1
    assert outbox(client)["items"][0]["status"] == "delivered"


def test_both_invoices_report_the_other_open_kind(client):
    a = mk(client, "deal_payment").json()
    mk(client, "commission")
    pay_via_sweep(client, a)
    assert client.deals.notifications[0]["other_open_kinds"] == ["commission"]


def test_webhook_delivers_inline_and_refund_notifies(client):
    inv = mk(client).json()
    r = post_event(client, {"event_id": "e1", "type": "payment.confirmed", "invoice_id": inv["id"]})
    assert r.status_code == 200
    assert [n["status"] for n in client.deals.notifications] == ["paid"]
    assert client.post(f"/v1/invoices/{inv['id']}/refund", headers=ADMIN).status_code == 200
    assert [n["status"] for n in client.deals.notifications] == ["paid", "refunded"]
    assert client.deals.notifications[1]["event_id"] == f"{inv['id']}:refunded"


def test_non_settling_transitions_enqueue_nothing(client):
    inv = mk(client).json()
    client.provider.seen(inv["provider_ref"])
    client.post("/v1/payments/sweep", headers=ADMIN)
    client.post(f"/v1/invoices/{inv['id']}/cancel", headers=BUYER)
    assert outbox(client)["total"] == 0


def test_outage_never_blocks_settlement_and_retries_with_backoff(client, clock):
    client.deals.fail_with = UpstreamUnavailable("rfq down")
    inv = mk(client).json()
    r = post_event(client, {"event_id": "e1", "type": "payment.confirmed", "invoice_id": inv["id"]})
    assert r.status_code == 200 and r.json()["invoice_status"] == "paid"
    assert client.get(f"/v1/invoices/{inv['id']}", headers=BUYER).json()["status"] == "paid"
    (row,) = outbox(client, "pending")["items"]
    assert row["attempts"] == 1 and "rfq down" in row["last_error"]  # inline attempt
    # not due yet (30 s backoff): the sweep does not touch it
    clock.advance(seconds=10)
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["outbox_retry"] == 0
    assert outbox(client, "pending")["items"][0]["attempts"] == 1
    clock.advance(seconds=25)  # due: attempt 2 fails, backoff doubles to 60 s
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["outbox_retry"] == 1
    row = outbox(client, "pending")["items"][0]
    assert row["attempts"] == 2
    clock.advance(seconds=50)
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["outbox_retry"] == 0  # still backing off
    client.deals.fail_with = None  # rfq is back
    clock.advance(seconds=20)
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["outbox_delivered"] == 1
    assert len(client.deals.notifications) == 1 and outbox(client, "delivered")["total"] == 1
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["outbox_delivered"] == 0  # exactly once


def test_dead_letter_after_max_attempts_and_requeue(client, clock):
    client.deals.fail_with = UpstreamUnavailable("rfq down")
    inv = mk(client).json()
    pay_via_sweep(client, inv)  # attempt 1
    for _ in range(10):
        clock.advance(hours=2)
        client.post("/v1/payments/sweep", headers=ADMIN)
    (dead,) = outbox(client, "dead")["items"]
    assert dead["attempts"] == 8 and outbox(client, "pending")["total"] == 0
    clock.advance(hours=2)
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["outbox_delivered"] == 0  # dead stays dead
    client.deals.fail_with = None
    assert client.post(f"/v1/payments/outbox/{dead['id']}/requeue", headers=ADMIN).json()["status"] == "pending"
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["outbox_delivered"] == 1
    assert client.post(f"/v1/payments/outbox/{dead['id']}/requeue", headers=ADMIN).status_code == 409
    assert client.post("/v1/payments/outbox/nope/requeue", headers=ADMIN).status_code == 404
    assert client.get("/v1/payments/outbox").status_code in (401, 403)
    assert client.get("/v1/payments/outbox", headers=BUYER).status_code == 403


def test_permanent_rejection_dead_letters_immediately(client):
    client.deals.fail_with = NotifyRejected("amount_mismatch", 422)
    inv = mk(client).json()
    out = pay_via_sweep(client, inv)
    assert out["outbox_dead"] == 1 and client.get(f"/v1/invoices/{inv['id']}", headers=BUYER).json()["status"] == "paid"
    assert outbox(client, "dead")["items"][0]["attempts"] == 1


def test_per_deal_order_is_kept(client, clock):
    client.deals.fail_with = UpstreamUnavailable("down")
    inv = mk(client).json()
    pay_via_sweep(client, inv)  # paid event stuck in the outbox
    client.post(f"/v1/invoices/{inv['id']}/refund", headers=ADMIN)  # refunded queued behind it
    client.deals.fail_with = None
    clock.advance(seconds=5)  # the paid event is still backing off -> refunded must not overtake it
    client.post("/v1/payments/sweep", headers=ADMIN)
    assert client.deals.notifications == []
    clock.advance(seconds=60)
    client.post("/v1/payments/sweep", headers=ADMIN)
    assert [n["status"] for n in client.deals.notifications] == ["paid", "refunded"]


def test_http_client_maps_rfq_answers_and_sends_internal_token():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        code = {"deal_ok": 200, "deal_gone": 404, "deal_bad": 422, "deal_5xx": 503, "deal_429": 429}[req.url.path.split("/")[4]]
        return httpx.Response(code, json={"error": {"code": "x"}})

    c = HttpDealClient("http://rfq", "tok", transport=httpx.MockTransport(handler))

    async def run():
        await c.notify_payment_status("deal_ok", {"event_id": "e"})
        for d in ("deal_gone", "deal_bad"):
            with pytest.raises(NotifyRejected):
                await c.notify_payment_status(d, {"event_id": "e"})
        for d in ("deal_5xx", "deal_429"):
            with pytest.raises(UpstreamUnavailable):
                await c.notify_payment_status(d, {"event_id": "e"})

    import asyncio
    asyncio.run(run())
    assert seen[0].url.path == "/v1/internal/deals/deal_ok/payment-status"
    assert seen[0].headers["x-internal-token"] == "tok"


def test_outbox_survives_without_client_support_for_unpaid_flow():
    """A deal that is never paid creates no outbox rows and no callbacks."""
    deals = MockDealClient({"deal_1": DEAL})
    with TestClient(create_app(make_settings(), provider=MockProvider(), deals=deals, clock=Clock())) as c:
        c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER)
        assert c.post("/v1/payments/sweep", headers=ADMIN).json()["outbox_delivered"] == 0
    assert deals.notifications == []


async def test_http_deal_client_quotes_deal_id_in_path():
    import httpx

    from ff_payments.clients.deals import HttpDealClient

    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.raw_path.decode())
        return httpx.Response(200, json={})

    c = HttpDealClient("http://rfq", "t", transport=httpx.MockTransport(handler))
    await c.notify_payment_status("../../v1/requests?x=1", {"event_id": "e"})
    await c.get_deal("a/b", "u1")
    assert seen == ["/v1/internal/deals/..%2F..%2Fv1%2Frequests%3Fx%3D1/payment-status", "/v1/deals/a%2Fb"]
