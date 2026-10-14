import pytest
from conftest import ADM, QUOTE, make_forwarder, make_quote, make_request, uh


def qpost(client, rid, user="fw", **over):
    return client.post(f"/v1/freight/requests/{rid}/quotes", headers=uh(user), json={**QUOTE, **over})


@pytest.fixture
def setup(client):
    fid = make_forwarder(client, "fw")
    req = make_request(client)
    return client, fid, req


def test_submit_quote_shape(setup):
    c, fid, req = setup
    q = make_quote(c, req["id"], "fw", amount="2450.5", breakdown=[{"label": "Ocean freight", "amount": "2000"}, {"label": "THC", "amount": "450.50"}])
    assert q["amount"] == "2450.50" and q["currency"] == "USD" and q["status"] == "submitted" and q["valid"] is True
    assert q["forwarder_id"] == fid and q["forwarder"]["company_name"] == "Gulf Star Logistics"
    assert q["breakdown"] == [{"label": "Ocean freight", "amount": "2000.00"}, {"label": "THC", "amount": "450.50"}]
    assert q["inclusions"] == ["Ocean freight", "Origin THC"] and q["revision"] == 1
    assert c.get(f"/v1/freight/requests/{req['id']}", headers=uh("buyer1")).json()["quote_count"] == 1


def test_only_matching_forwarders_may_quote(client):
    make_forwarder(client, "jo", lanes=[{"origin_country": "CN", "destination_country": "JO"}])
    make_forwarder(client, "air_only", modes=["air"])
    make_forwarder(client, "ddp", incoterms=["DDP"])
    req = make_request(client)
    for u in ("jo", "air_only", "ddp"):
        assert qpost(client, req["id"], u).status_code == 404, u  # request is invisible to them
    assert qpost(client, req["id"], "random").json()["error"]["code"] == "forwarder_required"
    assert qpost(client, req["id"], "buyer1").status_code == 403
    assert client.get(f"/v1/freight/requests/{req['id']}/quotes", headers=uh("buyer1")).json()["items"] == []


def test_no_quote_on_own_request(client):
    make_forwarder(client, "fw")
    own = make_request(client, user="fw")
    r = qpost(client, own["id"], "fw")
    assert r.status_code == 403 and r.json()["error"]["code"] == "own_request"


@pytest.mark.parametrize(
    "over",
    [
        {"amount": "0"},
        {"amount": "-3"},
        {"amount": "10.999"},
        {"amount": "1000000000"},
        {"amount": "abc"},
        {"currency": "usd"},
        {"transit_days": 0},
        {"transit_days": 366},
        {"valid_days": 0},
        {"valid_days": 91},
        {"inclusions": ["x"] * 11},
        {"terms": "x" * 1001},
        {"extra": 1},
        {"forwarder_id": "fwd_other"},
        {"status": "accepted"},
    ],
)
def test_quote_validation(setup, over):
    c, _, req = setup
    assert qpost(c, req["id"], **over).status_code == 422


def test_currency_mismatch_and_breakdown_sum(setup):
    c, _, req = setup
    r = qpost(c, req["id"], currency="EUR")
    assert r.status_code == 422 and r.json()["error"]["code"] == "currency_mismatch"
    r = qpost(c, req["id"], breakdown=[{"label": "Freight", "amount": "100"}])
    assert r.status_code == 422 and r.json()["error"]["code"] == "breakdown_mismatch"
    # exact decimal arithmetic: 0.10 + 0.20 == 0.30 (no float drift)
    ok = qpost(c, req["id"], amount="0.30", breakdown=[{"label": "A fee", "amount": "0.10"}, {"label": "B fee", "amount": "0.20"}])
    assert ok.status_code == 201


@pytest.mark.parametrize(
    "over",
    [
        {"terms": "pay to iban, mail agent@freight.com"},
        {"terms": "call 009647701234567"},
        {"terms": "see https://freight.example/terms"},
        {"inclusions": ["whatsapp support"]},
        {"exclusions": ["site.com handling"]},
        {"breakdown": [{"label": "firearm handling", "amount": "10"}], "amount": "10"},
    ],
)
def test_quote_screening(setup, over):
    c, _, req = setup
    r = qpost(c, req["id"], **over)
    assert r.status_code == 422 and r.json()["error"]["code"] == "content_rejected"
    assert "agent@freight" not in r.text


def test_duplicate_quote_conflicts_then_revise(setup):
    c, _, req = setup
    q = make_quote(c, req["id"], "fw")
    r = qpost(c, req["id"], "fw")
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_exists"
    rv = c.put(f"/v1/freight/quotes/{q['id']}", headers=uh("fw"), json={**QUOTE, "amount": "2300", "transit_days": 25})
    assert rv.status_code == 200 and rv.json()["amount"] == "2300.00" and rv.json()["revision"] == 2
    assert c.put(f"/v1/freight/quotes/{q['id']}", headers=uh("fw"), json={**QUOTE, "currency": "EUR"}).status_code == 422
    assert c.put(f"/v1/freight/quotes/{q['id']}", headers=uh("other_fw"), json=QUOTE).status_code == 403  # not a forwarder
    make_forwarder(c, "fw2")
    assert c.put(f"/v1/freight/quotes/{q['id']}", headers=uh("fw2"), json=QUOTE).status_code == 404  # not the owner


def test_withdraw_and_revive(setup):
    c, _, req = setup
    q = make_quote(c, req["id"], "fw")
    w = c.post(f"/v1/freight/quotes/{q['id']}/withdraw", headers=uh("fw"))
    assert w.json()["status"] == "withdrawn" and w.json()["valid"] is False
    assert c.post(f"/v1/freight/quotes/{q['id']}/withdraw", headers=uh("fw")).json()["status"] == "withdrawn"  # idempotent
    assert c.get(f"/v1/freight/requests/{req['id']}", headers=uh("buyer1")).json()["quote_count"] == 0
    assert c.get(f"/v1/freight/requests/{req['id']}/quotes", headers=uh("buyer1")).json()["items"] == []
    withdrawn = c.get(f"/v1/freight/requests/{req['id']}/quotes", headers=uh("buyer1"), params={"status": "withdrawn"}).json()["items"]
    assert [i["id"] for i in withdrawn] == [q["id"]]
    assert c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1")).json()["error"]["code"] == "quote_not_available"
    back = c.put(f"/v1/freight/quotes/{q['id']}", headers=uh("fw"), json=QUOTE)
    assert back.json()["status"] == "submitted"
    assert c.get(f"/v1/freight/requests/{req['id']}", headers=uh("buyer1")).json()["quote_count"] == 1


def test_quote_cap_per_request(make_client):
    from conftest import NO_LIMITS

    c = make_client(**{**NO_LIMITS, "max_quotes_per_request": 2})
    for u in ("a", "b", "c"):
        make_forwarder(c, u)
    req = make_request(c)
    make_quote(c, req["id"], "a")
    make_quote(c, req["id"], "b")
    r = qpost(c, req["id"], "c")
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_limit_reached"


def test_list_quotes_owner_only_and_paginated(client):
    users = [f"f{i}" for i in range(5)]
    for u in users:
        make_forwarder(client, u)
    req = make_request(client)
    ids = [make_quote(client, req["id"], u)["id"] for u in users]
    assert client.get(f"/v1/freight/requests/{req['id']}/quotes", headers=uh("f0")).status_code == 404
    assert client.get(f"/v1/freight/requests/{req['id']}/quotes", headers=uh("stranger")).status_code == 404
    seen, cur = [], None
    while True:
        r = client.get(f"/v1/freight/requests/{req['id']}/quotes", headers=uh("buyer1"), params={"limit": 2, **({"cursor": cur} if cur else {})}).json()
        seen += [i["id"] for i in r["items"]]
        assert all("forwarder" in i for i in r["items"])
        cur = r["next_cursor"]
        if not cur:
            break
    assert seen == ids[::-1]


def test_get_quote_access(setup):
    c, _, req = setup
    q = make_quote(c, req["id"], "fw")
    for u in ("fw", "buyer1"):
        assert c.get(f"/v1/freight/quotes/{q['id']}", headers=uh(u)).status_code == 200
    assert c.get(f"/v1/freight/quotes/{q['id']}", headers=uh("stranger")).status_code == 404
    mine = c.get("/v1/freight/forwarders/me/quotes", headers=uh("fw")).json()["items"]
    assert [i["id"] for i in mine] == [q["id"]]
    assert c.get("/v1/freight/forwarders/me/quotes", headers=uh("fw"), params={"status": "accepted"}).json()["items"] == []
    assert c.get("/v1/freight/forwarders/me/quotes", headers=uh("buyer1")).status_code == 403


def test_suspended_forwarder_cannot_quote(setup):
    c, fid, req = setup
    q = make_quote(c, req["id"], "fw")
    c.post(f"/v1/admin/freight/forwarders/{fid}/suspend", headers=ADM, json={"reason": "fraud suspicion"})
    r = qpost(c, make_request(c)["id"], "fw")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forwarder_suspended"
    assert c.put(f"/v1/freight/quotes/{q['id']}", headers=uh("fw"), json=QUOTE).status_code == 403
    assert c.get("/v1/freight/forwarders/me/inbox", headers=uh("fw")).status_code == 403
    assert c.get("/v1/freight/forwarders/me", headers=uh("fw")).json()["status"] == "suspended"
    # buyer: suspended forwarder's quote is excluded from comparison and cannot be accepted
    cmp_ = c.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1")).json()
    assert cmp_["items"] == [] and cmp_["excluded"] == [{"quote_id": q["id"], "reason": "forwarder_suspended"}]
    assert c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1")).json()["error"]["code"] == "forwarder_suspended"


def test_quote_validity_lapses(setup, clock):
    c, _, req = setup
    q = make_quote(c, req["id"], "fw", valid_days=2)
    clock.advance(days=3)
    got = c.get(f"/v1/freight/quotes/{q['id']}", headers=uh("buyer1")).json()
    assert got["valid"] is False and got["status"] == "submitted"
    r = c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_expired"
    cmp_ = c.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1")).json()
    assert cmp_["excluded"] == [{"quote_id": q["id"], "reason": "quote_expired"}]
    c.put(f"/v1/freight/quotes/{q['id']}", headers=uh("fw"), json=QUOTE)  # revising renews validity
    assert c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1")).status_code == 200
    assert ADM
