import asyncio

import pytest
from conftest import ADMIN, BUYER, mk
from sqlalchemy import select

from ff_payments import webhooks
from ff_payments.db import LedgerEntryRow
from ff_payments.domain.enums import InvoiceStatus as S
from ff_payments.domain.errors import Conflict


def test_unicode_digit_timestamp_is_a_401_not_a_crash():
    with pytest.raises(webhooks.InvalidSignature):
        webhooks.verify("s", b"b", "t=²,v1=ab", now_ts=1, tolerance=300)


def test_stale_concurrent_settlement_cannot_double_post_ledger(client):
    inv = mk(client).json()
    svc = client.app.state.service

    async def run():
        from ff_payments.db import InvoiceRow
        async with svc.sessions() as s1, svc.sessions() as s2:
            r1 = await s1.get(InvoiceRow, inv["id"])
            r2 = await s2.get(InvoiceRow, inv["id"])
            await svc._move(s1, r1, S.PAID)
            await s1.commit()
            with pytest.raises(Conflict):
                await svc._move(s2, r2, S.PAID)  # stale view: must not post a second ledger group
            await s2.rollback()
        async with svc.sessions() as s:
            return (await s.execute(select(LedgerEntryRow).where(LedgerEntryRow.invoice_id == inv["id"]))).scalars().all()

    assert len(asyncio.run(run())) == 2  # one balanced group (2 legs)


def test_oversized_webhook_body_is_refused_before_signature_work(client):
    r = client.post("/v1/payments/webhooks/mock", content=b"x" * (65 * 1024))
    assert r.status_code == 422 and r.json()["error"]["code"] == "payload_too_large"


def test_payee_never_sees_payers_memo_via_api(client):
    inv = mk(client, memo="payer only").json()
    payee = inv["payee"]
    assert client.get(f"/v1/invoices/{inv['id']}", headers={"X-User-Id": "buyer1"}).json()["user_memo"] == "payer only"
    seen = client.get(f"/v1/invoices/{inv['id']}", headers={"X-User-Id": payee}).json()
    assert seen["user_memo"] is None
    items = client.get("/v1/invoices", headers={"X-User-Id": payee}).json()["items"]
    assert items and all(i["user_memo"] is None for i in items)


def test_overlong_user_id_header_is_rejected(client):
    assert client.get("/v1/invoices", headers={"X-User-Id": "u" * 200}).status_code == 401


def _client(clock, **over):
    from conftest import DEAL, make_settings
    from fastapi.testclient import TestClient

    from ff_payments.clients.deals import MockDealClient
    from ff_payments.main import create_app
    from ff_payments.providers.mock import MockProvider

    return TestClient(create_app(make_settings(**over), provider=MockProvider(),
                                 deals=MockDealClient({"deal_1": DEAL, "deal_2": {**DEAL, "id": "deal_2"},
                                                       "deal_3": {**DEAL, "id": "deal_3"}}), clock=clock))


def test_open_invoice_cap_per_payer(clock):
    with _client(clock, max_open_invoices_per_user=2) as c:
        assert mk(c, deal_id="deal_1").status_code == 201
        assert mk(c, deal_id="deal_2").status_code == 201
        r = mk(c, deal_id="deal_3")
        assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_open_invoices"
        assert mk(c, deal_id="deal_1").status_code == 200  # idempotent hit is free
        first = c.get("/v1/invoices", headers=BUYER).json()["items"][0]["id"]
        assert c.post(f"/v1/invoices/{first}/cancel", headers=BUYER).status_code == 200
        assert mk(c, deal_id="deal_3").status_code == 201  # cancelling frees a slot


def test_daily_invoice_cap_counts_cancelled_too(clock):
    with _client(clock, max_invoices_per_user_per_day=2) as c:
        for _ in range(2):
            inv = mk(c).json()
            assert c.post(f"/v1/invoices/{inv['id']}/cancel", headers=BUYER).status_code == 200
        r = mk(c)
        assert r.status_code == 429 and r.json()["error"]["code"] == "daily_invoice_limit"
        clock.advance(hours=25)
        assert mk(c).status_code == 201


def test_prune_removes_only_inert_old_records(clock):
    from ff_payments.db import OutboxEventRow, PaymentAttemptRow, WebhookEventRow

    with _client(clock) as c:
        svc = c.app.state.service
        paid = mk(c, deal_id="deal_1").json()
        dead = mk(c, deal_id="deal_2").json()
        assert c.post(f"/v1/invoices/{dead['id']}/cancel", headers=BUYER).status_code == 200
        svc.provider.confirm(paid["provider_ref"]) if hasattr(svc.provider, "confirm") else None
        post_event_paid = {"event_id": "e1", "type": "payment.confirmed", "invoice_id": paid["id"]}
        from conftest import post_event
        c.clock = clock
        assert post_event(c, post_event_paid).status_code == 200
        post_event(c, {"event_id": "e2", "type": "payment.failed", "invoice_id": dead["id"]})
        clock.advance(days=400)
        assert c.post("/v1/payments/sweep", headers=ADMIN).status_code == 200

        async def counts():
            async with svc.sessions() as s:
                return [len((await s.execute(select(t))).scalars().all())
                        for t in (WebhookEventRow, OutboxEventRow, PaymentAttemptRow)]

        # paid invoice: webhook event + attempt kept; undelivered/delivered outbox for the paid deal pruned only if delivered
        ev, ob, att = asyncio.run(counts())
        assert ev == 1  # e1 (paid) kept, e2 (failed invoice) pruned
        assert att == 1  # paid invoice's attempt kept, cancelled invoice's attempt pruned
        assert ob == 0  # delivered long ago (mock deal client accepts)
