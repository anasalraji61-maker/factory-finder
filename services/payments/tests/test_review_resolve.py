"""Admin review-queue resolution: settle / refund_flag / dismiss (CAS, audit, idempotent replay, mismatch guard)."""

from conftest import ADMIN, BUYER, mk, post_event

REV = {**ADMIN, "X-Reviewer": "alice"}


def _late(client, clock):
    inv = mk(client).json()
    clock.advance(minutes=61)
    assert post_event(client, {"event_id": "l1", "type": "payment.confirmed", "invoice_id": inv["id"],
                               "tx_ref": "txL"}).json()["status"] == "review"
    return inv


def _mismatch(client, got="374.00"):
    inv = mk(client).json()
    r = post_event(client, {"event_id": "m1", "type": "payment.confirmed", "invoice_id": inv["id"],
                            "amount": {"amount": got, "currency": "USD"}})
    assert r.json()["status"] == "review"
    return inv


def _res(client, inv, body, headers=REV):
    return client.post(f"/v1/payments/review/{inv['id']}/resolve", json=body, headers=headers)


def _inv(client, inv):
    return client.get(f"/v1/invoices/{inv['id']}", headers=BUYER).json()


def _queue(client):
    return client.get("/v1/payments/review", headers=ADMIN).json()["total"]


def test_requires_admin_and_valid_body(client, clock):
    inv = _late(client, clock)
    assert _res(client, inv, {"action": "dismiss"}, BUYER).status_code == 403
    assert _res(client, inv, {"action": "dismiss"}, {}).status_code == 403
    for bad in ({"action": "nuke"}, {}, {"action": "dismiss", "note": "x" * 501}, {"action": "dismiss", "extra": 1},
                {"action": "dismiss", "note": "a\x00b"}, {"action": "dismiss", "confirm_amount_mismatch": "yes"}):
        assert _res(client, inv, bad).status_code == 422, bad
    assert _queue(client) == 1


def test_dismiss_leaves_queue_audits_and_replays(client, clock):
    inv = _late(client, clock)
    r = _res(client, inv, {"action": "dismiss", "note": "  not ours "})
    assert r.status_code == 200
    b = r.json()
    assert b["action"] == "dismiss" and b["note"] == "not ours" and b["reviewer"] == "alice"
    assert b["previous_reason"] == "late_payment_review" and b["status_reason"] == "review_dismissed"
    assert _queue(client) == 0 and _inv(client, inv)["status"] == "expired"
    again = _res(client, inv, {"action": "dismiss", "note": "other note"}, {**ADMIN, "X-Reviewer": "bob"})
    assert again.status_code == 200 and again.json() == b  # same stored result, no second audit row
    other = _res(client, inv, {"action": "settle"})
    assert other.status_code == 409 and other.json()["error"]["code"] == "already_resolved"


def test_reviewer_sanitised_and_defaults(client, clock):
    inv = _late(client, clock)
    r = _res(client, inv, {"action": "dismiss"}, {**ADMIN, "X-Reviewer": "bob@x.com <b>"})
    assert r.json()["reviewer"] == "bobx.comb"
    inv2 = _late2 = mk(client, deal_id="deal_1", kind="deal_payment").json()
    client.post(f"/v1/invoices/{inv2['id']}/cancel", headers=BUYER)
    post_event(client, {"event_id": "c9", "type": "payment.confirmed", "invoice_id": inv2["id"]})
    assert _res(client, inv2, {"action": "dismiss"}, ADMIN).json()["reviewer"] == "admin"


def test_settle_late_payment_books_ledger_and_outbox_once(client, clock):
    inv = _late(client, clock)
    r = _res(client, inv, {"action": "settle", "note": "verified on chain"})
    assert r.status_code == 200 and r.json()["invoice_status"] == "paid"
    got = _inv(client, inv)
    assert got["status"] == "paid" and got["status_reason"] == "review_settled" and got["paid_at"]
    assert client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()["total"] == 2
    box = client.get("/v1/payments/outbox", headers=ADMIN).json()
    assert [e["event_id"] for e in box["items"]] == [f"{inv['id']}:paid"]
    assert _res(client, inv, {"action": "settle"}).json() == r.json()
    assert client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()["total"] == 2
    assert _queue(client) == 0


def test_refund_flag_leaves_queue_without_ledger(client, clock):
    inv = _late(client, clock)
    r = _res(client, inv, {"action": "refund_flag", "note": "refund to payer"})
    assert r.status_code == 200 and r.json()["status_reason"] == "refund_flagged"
    got = _inv(client, inv)
    assert got["status"] == "expired" and got["status_reason"] == "refund_flagged"
    assert client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()["total"] == 0
    assert _queue(client) == 0


def test_not_in_review_and_unknown(client):
    inv = mk(client).json()
    r = _res(client, inv, {"action": "dismiss"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_in_review"
    r = client.post("/v1/payments/review/inv_nope/resolve", json={"action": "dismiss"}, headers=ADMIN)
    assert r.status_code == 404


def test_amount_mismatch_settle_guards(client):
    inv = _mismatch(client)
    body = {"action": "settle", "note": "customer short-paid fees", "confirm_amount_mismatch": True,
            "received_amount": {"amount": "374.00", "currency": "USD"}}
    codes = {}
    for key, bad in {
        "note_required": {**body, "note": None},
        "amount_mismatch_confirmation_required": {**body, "confirm_amount_mismatch": False},
        "received_amount_required": {k: v for k, v in body.items() if k != "received_amount"},
        "amount_outside_tolerance": {**body, "received_amount": {"amount": "300.00", "currency": "USD"}},
    }.items():
        r = _res(client, inv, bad)
        codes[key] = (r.status_code, r.json()["error"]["code"])
    assert all(v == (422, k) for k, v in codes.items()), codes
    wrong_cur = _res(client, inv, {**body, "received_amount": {"amount": "374.00", "currency": "EUR"}})
    assert wrong_cur.json()["error"]["code"] == "received_amount_required"
    assert _queue(client) == 1 and _inv(client, inv)["status"] == "awaiting_payment"
    ok = _res(client, inv, body)
    assert ok.status_code == 200
    b = ok.json()
    assert b["confirm_amount_mismatch"] is True and b["received_amount"] == {"amount": "374.00", "currency": "USD"}
    got = _inv(client, inv)
    assert got["status"] == "paid" and got["status_reason"] == "review_settled"


def test_amount_mismatch_dismiss_and_refund_need_no_confirmation(client):
    inv = _mismatch(client)
    assert _res(client, inv, {"action": "refund_flag"}).status_code == 200
    inv2 = _mismatch2 = mk(client, deal_id="deal_1", kind="deal_payment").json()
    post_event(client, {"event_id": "m2", "type": "payment.confirmed", "invoice_id": inv2["id"],
                        "amount": {"amount": "1.00", "currency": "USD"}})
    assert _res(client, inv2, {"action": "dismiss"}).status_code == 200


async def test_concurrent_settles_book_once(tmp_path):
    import asyncio

    from test_concurrency import Boot

    async with Boot(tmp_path) as b:
        inv = (await b.c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER)).json()
        b.clock.advance(minutes=61)
        await b.event({"event_id": "l1", "type": "payment.confirmed", "invoice_id": inv["id"], "tx_ref": "txL"})
        rs = await asyncio.gather(*[b.c.post(f"/v1/payments/review/{inv['id']}/resolve", json={"action": "settle"},
                                             headers=REV) for _ in range(6)])
        assert {r.status_code for r in rs} <= {200, 409}, [r.text for r in rs]
        assert any(r.status_code == 200 for r in rs)
        assert len({r.text for r in rs if r.status_code == 200}) == 1
        assert await b.ledger(inv["id"]) == 2
        assert len((await b.c.get("/v1/payments/outbox", headers=ADMIN)).json()["items"]) == 1
