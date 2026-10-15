"""QA round K: payments callback ordering, replay (also after a dead-letter requeue), mismatches leave no trace."""

from test_deals import cb, make_deal, status


def events(client, d):
    return client.get(f"/v1/deals/{d['id']}/events", headers={"X-User-Id": d["buyer_id"]}).json()["items"]


def test_refunded_before_paid_same_invoice_then_replayed_paid_is_ignored(client):
    d = make_deal(client)
    assert cb(client, d, status="refunded").json()["deal_status"] == "refunded"
    late = cb(client, d)  # reordered 'paid' of the refunded invoice
    assert late.json()["outcome"] == "ignored" and late.json()["deal_status"] == "refunded"


def test_replay_after_dead_letter_is_duplicate_not_second_transition(client):
    d = make_deal(client)
    assert cb(client, d, event_id="e1").json()["outcome"] == "applied"
    # payments dead-lettered, then an operator requeued the same event_id: harmless
    for _ in range(3):
        r = cb(client, d, event_id="e1")
        assert r.json()["outcome"] == "duplicate" and r.json()["deal_status"] == "paid"
    assert len(events(client, d)) == 1


def test_amount_mismatch_leaves_no_event_so_corrected_replay_applies(client):
    d = make_deal(client)
    bad = {"amount": "1.00", "currency": d["subtotal"]["currency"]}
    r = cb(client, d, event_id="e1", amount=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "amount_mismatch"
    assert status(client, d) == "pending_payment" and events(client, d) == []
    assert cb(client, d, event_id="e1").json()["outcome"] == "applied"  # same id, right amount


def test_commission_refund_then_repaid_with_new_invoice(client):
    d = make_deal(client)
    cb(client, d, "commission", inv="inv_c1")
    assert cb(client, d, "commission", "refunded", inv="inv_c1").json()["deal_status"] == "pending_payment"
    again = cb(client, d, "commission", inv="inv_c2")  # a NEW invoice for the same kind may settle it again
    assert again.json()["deal_status"] == "paid" and again.json()["outcome"] == "applied"
    stale = cb(client, d, "commission", inv="inv_c1")  # old replay still cannot undo it
    assert stale.json()["outcome"] == "ignored" or stale.json()["deal_status"] == "paid"


def test_paid_then_refunded_sequence_event_log_order(client):
    d = make_deal(client)
    cb(client, d, event_id="a")
    cb(client, d, status="refunded", event_id="b")
    cb(client, d, event_id="c")  # replay of paid, new id (e.g. reorder after dead-letter replay)
    ev = events(client, d)
    assert [e["seq"] for e in ev] == [1, 2, 3] and status(client, d) == "refunded"
    assert ev[2]["data"]["outcome"] == "ignored"
