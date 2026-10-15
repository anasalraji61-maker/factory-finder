import asyncio

import pytest
from conftest import mk
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
