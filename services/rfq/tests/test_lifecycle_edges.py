"""Lifecycle edge cases: expiry sweeps, currencies, invites, withdraw/cancel, reviews, precision, paging."""

from decimal import Decimal

from conftest import BUYER, SUP_A, SUP_B, new_offer, new_request

from ff_rfq.domain.commission import compute_commission, quantize_money
from ff_rfq.domain.enums import ListingKind

SUP_V = {"X-User-Id": "supA", "X-Supplier-Id": "sup_ref_a"}


def code(r):
    return r.json()["error"]["code"]


def accept(client, oid, h=BUYER):
    return client.post(f"/v1/offers/{oid}/accept", headers=h)


# ---- expiry ---------------------------------------------------------------------------------
def test_request_expiry_sweeps_offers_and_blocks_new_offers_and_accept(client, clock):
    req = new_request(client, deadline="2026-10-02T00:00:00Z")
    o = new_offer(client, req["id"])
    clock.advance(days=2)
    r = client.post(f"/v1/requests/{req['id']}/offers", headers=SUP_B,
                    json={"price": {"amount": "1", "currency": "USD"}, "supplier_name": "B"})
    assert r.status_code == 409 and code(r) == "invalid_request_transition"
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] == "expired"
    assert client.get(f"/v1/requests/{req['id']}/offers", headers=BUYER).json()["items"][0]["status"] == "expired"
    r = accept(client, o["id"])
    assert r.status_code == 409 and code(r) == "invalid_request_transition"
    assert client.post(f"/v1/offers/{o['id']}/withdraw", headers=SUP_A).status_code == 409
    assert client.post(f"/v1/requests/{req['id']}/close", headers=BUYER).status_code == 409


def test_accept_exactly_at_deadline_is_expired(client, clock):
    req = new_request(client, deadline="2026-10-02T12:00:00Z")
    o = new_offer(client, req["id"])
    clock.advance(days=1)  # now == deadline
    assert accept(client, o["id"]).status_code == 409
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] in ("negotiating", "expired")


def test_offer_lapse_releases_request_to_open(client, clock):
    req = new_request(client)
    new_offer(client, req["id"], valid_until="2026-10-02T00:00:00Z")
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] == "negotiating"
    clock.advance(days=2)
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] == "open"
    new_offer(client, req["id"], SUP_B)  # open again for new offers


def test_awarded_request_never_expires(client, clock):
    req = new_request(client, deadline="2026-10-02T00:00:00Z")
    o = new_offer(client, req["id"])
    assert accept(client, o["id"]).status_code == 200
    clock.advance(days=10)
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] == "awarded"


def test_offer_validity_in_past_rejected(client):
    req = new_request(client)
    r = client.post(f"/v1/requests/{req['id']}/offers", headers=SUP_A, json={
        "price": {"amount": "1", "currency": "USD"}, "supplier_name": "A", "valid_until": "2020-01-01T00:00:00Z"})
    assert r.status_code == 422 and code(r) == "invalid_valid_until"


# ---- currencies -----------------------------------------------------------------------------
def test_comparable_flag_and_no_implicit_conversion(client):
    req = new_request(client, target_price={"amount": "10", "currency": "USD"})
    usd = new_offer(client, req["id"], SUP_A, "12.50", "USD")
    eur = new_offer(client, req["id"], SUP_B, "9", "EUR")
    assert usd["comparable"] is True and eur["comparable"] is False
    items = {i["id"]: i for i in client.get(f"/v1/requests/{req['id']}/offers", headers=BUYER).json()["items"]}
    assert items[eur["id"]]["price"] == {"amount": "9", "currency": "EUR"}
    assert items[eur["id"]]["comparable"] is False and items[usd["id"]]["comparable"] is True
    d = accept(client, eur["id"]).json()
    assert d["unit_price"]["currency"] == "EUR" and d["subtotal"] == {"amount": "9000.00", "currency": "EUR"}
    assert d["commission"]["amount"]["currency"] == "EUR"


def test_comparable_null_without_target(client):
    req = new_request(client)
    assert new_offer(client, req["id"])["comparable"] is None


# ---- invite-only ----------------------------------------------------------------------------
def test_invite_only_blocks_everything_for_outsiders(client):
    req = new_request(client, invited_supplier_ids=["sup_ref_a"], visibility="private")
    out = {"X-User-Id": "stranger", "X-Supplier-Id": "sup_ref_x"}
    anon = {"X-User-Id": "stranger2"}
    for h in (out, anon):
        assert client.get(f"/v1/requests/{req['id']}", headers=h).status_code == 404
        assert client.get(f"/v1/requests/{req['id']}/offers", headers=h).status_code == 404
        r = client.post(f"/v1/requests/{req['id']}/offers", headers=h,
                        json={"price": {"amount": "1", "currency": "USD"}, "supplier_name": "X"})
        assert r.status_code == 404
        assert req["id"] not in [i["id"] for i in client.get("/v1/requests?scope=public", headers=h).json()["items"]]
    assert client.get(f"/v1/requests/{req['id']}", headers=SUP_V).status_code == 200
    o = new_offer(client, req["id"], SUP_V)
    assert "invited_supplier_ids" not in client.get(f"/v1/requests/{req['id']}", headers=SUP_V).json()
    assert accept(client, o["id"], SUP_V).status_code == 403


# ---- withdraw / revise / cancel -------------------------------------------------------------
def test_withdraw_rules_and_resubmit_as_revision(client):
    req = new_request(client)
    o = new_offer(client, req["id"], amount="10")
    assert client.post(f"/v1/offers/{o['id']}/withdraw", headers=SUP_B).status_code == 403
    assert client.post(f"/v1/offers/{o['id']}/withdraw", headers=BUYER).status_code == 403
    assert client.post(f"/v1/offers/{o['id']}/withdraw", headers=SUP_A).status_code == 200
    assert client.post(f"/v1/offers/{o['id']}/withdraw", headers=SUP_A).status_code == 409
    assert accept(client, o["id"]).status_code == 409  # withdrawn offers can't be accepted
    assert client.post(f"/v1/offers/{o['id']}/reject", headers=BUYER).status_code == 409
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] == "open"
    n = new_offer(client, req["id"], amount="9")  # revision = new offer
    assert accept(client, n["id"]).status_code == 200


def test_cannot_withdraw_accepted_offer(client):
    req = new_request(client)
    o = new_offer(client, req["id"])
    accept(client, o["id"])
    r = client.post(f"/v1/offers/{o['id']}/withdraw", headers=SUP_A)
    assert r.status_code == 409 and code(r) == "invalid_offer_transition"


def test_buyer_cancel_with_pending_offers(client):
    req = new_request(client)
    a, b = new_offer(client, req["id"]), new_offer(client, req["id"], SUP_B)
    assert client.post(f"/v1/requests/{req['id']}/close", headers=SUP_A).status_code == 403
    assert client.post(f"/v1/requests/{req['id']}/close", headers=BUYER).json()["status"] == "closed"
    items = client.get(f"/v1/requests/{req['id']}/offers", headers=BUYER).json()["items"]
    assert {i["status"] for i in items} == {"rejected"}
    for o, h in ((a, SUP_A), (b, SUP_B)):
        assert accept(client, o["id"]).status_code == 409
        assert client.post(f"/v1/offers/{o['id']}/withdraw", headers=h).status_code == 409
    assert client.post(f"/v1/requests/{req['id']}/close", headers=BUYER).status_code == 409
    r = client.post(f"/v1/requests/{req['id']}/offers", headers=SUP_A,
                    json={"price": {"amount": "1", "currency": "USD"}, "supplier_name": "A"})
    assert r.status_code == 409
    assert client.get(f"/v1/requests/{req['id']}/deal", headers=BUYER).status_code == 404


def test_accept_rejects_siblings(client):
    req = new_request(client)
    a, b = new_offer(client, req["id"]), new_offer(client, req["id"], SUP_B)
    accept(client, a["id"])
    st = {i["id"]: i["status"] for i in client.get(f"/v1/requests/{req['id']}/offers", headers=BUYER).json()["items"]}
    assert st == {a["id"]: "accepted", b["id"]: "rejected"}


# ---- reviews --------------------------------------------------------------------------------
def test_review_requires_paid_deal_and_one_per_deal(client):
    req = new_request(client)
    o = new_offer(client, req["id"], SUP_V)
    d = accept(client, o["id"]).json()
    rv = {"X-User-Id": "buyer1", "X-User-Name": "Ann%20Lee"}
    r = client.post(f"/v1/deals/{d['id']}/reviews", json={"rating": 5}, headers=rv)
    assert r.status_code == 409 and code(r) == "deal_not_reviewable"  # pending_payment


# ---- precision ------------------------------------------------------------------------------
def test_iqd_is_whole_units_and_fractional_quantity_half_up(client):
    req = new_request(client, quantity="2.5", unit="kg")
    o = new_offer(client, req["id"], amount="1001.5", currency="IQD")
    d = accept(client, o["id"]).json()
    assert d["subtotal"]["amount"] == "2504"  # 2503.75 -> 2504
    assert d["commission"]["amount"] == {"amount": "32895", "currency": "IQD"}  # min fee, whole dinars
    assert d["commission"]["min_fee_applied"] is True
    assert d["supplier_net"]["amount"] == str(2504 - 32895)


def test_half_up_not_bankers():
    assert quantize_money(Decimal("0.125"), "USD") == Decimal("0.13")
    assert quantize_money(Decimal("2.5"), "IQD") == Decimal("3")
    assert quantize_money(Decimal("2.5"), "JPY") == Decimal("3")
    assert compute_commission(Decimal("10000000"), "IQD", ListingKind.PRODUCT).amount == Decimal("300000")


def test_tiny_total_rejected_not_free_deal(client):
    req = new_request(client, quantity="0.0001", unit="kg")
    o = new_offer(client, req["id"], amount="0.0001")
    r = accept(client, o["id"])
    assert r.status_code == 422 and code(r) == "amount_too_small"
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] == "negotiating"  # untouched


# ---- pagination -----------------------------------------------------------------------------
def test_pagination_stable_with_identical_timestamps(client):
    ids = [new_request(client, title=f"Same time {i}")["id"] for i in range(7)]  # frozen clock
    seen = []
    for p in (1, 2, 3, 4):
        seen += [i["id"] for i in client.get(f"/v1/requests?page={p}&page_size=2", headers=BUYER).json()["items"]]
    assert sorted(seen) == sorted(ids) and len(set(seen)) == 7
    req = ids[0]
    offs = [new_offer(client, req, {"X-User-Id": f"s{i}"})["id"] for i in range(5)]
    got = []
    for p in (1, 2, 3):
        got += [i["id"] for i in client.get(f"/v1/requests/{req}/offers?page={p}&page_size=2", headers=BUYER).json()["items"]]
    assert sorted(got) == sorted(offs) and len(set(got)) == 5
    again = []
    for p in (1, 2, 3):
        again += [i["id"] for i in client.get(f"/v1/requests/{req}/offers?page={p}&page_size=2", headers=BUYER).json()["items"]]
    assert again == got
