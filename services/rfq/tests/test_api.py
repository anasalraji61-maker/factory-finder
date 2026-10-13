from conftest import BUYER, SUP_A, SUP_B, new_offer, new_request


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "service": "rfq", "version": "0.1.0"}


def test_auth_required(client):
    r = client.get("/v1/requests")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"
    assert client.post("/v1/requests", json={}).status_code == 401


def test_validation_error_shape(client):
    r = client.post("/v1/requests", json={"kind": "bogus", "title": "x", "quantity": "-1"}, headers=BUYER)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_full_lifecycle_with_commission(client):
    req = new_request(client, target_price={"amount": "11", "currency": "USD"})
    assert req["status"] == "open" and req["quantity"] == "1000" and req["offers_count"] == 0
    o1 = new_offer(client, req["id"], SUP_A, "12.50")
    o2 = new_offer(client, req["id"], SUP_B, "13.00", incoterm="FOB", lead_time_days=20, moq=500)
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] == "negotiating"
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["offers_count"] == 2
    assert client.get(f"/v1/requests/{req['id']}/offers", headers=BUYER).json()["total"] == 2
    assert client.get(f"/v1/requests/{req['id']}/offers", headers=SUP_A).json()["total"] == 1  # own only

    deal = client.post(f"/v1/offers/{o1['id']}/accept", headers=BUYER)
    assert deal.status_code == 200, deal.text
    d = deal.json()
    assert d["subtotal"] == {"amount": "12500.00", "currency": "USD"}
    assert d["commission"]["rate"] == "0.03" and d["commission"]["amount"]["amount"] == "375.00"
    assert d["supplier_net"]["amount"] == "12125.00" and d["status"] == "pending_payment"

    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] == "awarded"
    offers = {o["id"]: o["status"] for o in client.get(f"/v1/requests/{req['id']}/offers", headers=BUYER).json()["items"]}
    assert offers == {o1["id"]: "accepted", o2["id"]: "rejected"}
    for who in (BUYER, SUP_A):
        assert client.get(f"/v1/deals/{d['id']}", headers=who).json()["id"] == d["id"]
    assert client.get(f"/v1/deals/{d['id']}", headers=SUP_B).status_code == 404


def test_min_fee_and_kind_rate(client):
    req = new_request(client, kind="production_line", quantity="1", unit="line")
    o = new_offer(client, req["id"], amount="100000")
    d = client.post(f"/v1/offers/{o['id']}/accept", headers=BUYER).json()
    assert d["commission"]["amount"]["amount"] == "4000.00"
    small = new_request(client, quantity="2")
    o = new_offer(client, small["id"], amount="10")
    d = client.post(f"/v1/offers/{o['id']}/accept", headers=BUYER).json()
    assert d["commission"]["amount"]["amount"] == "25.00" and d["commission"]["min_fee_applied"]


def test_ownership_rules(client):
    req = new_request(client)
    assert client.post(f"/v1/requests/{req['id']}/offers", headers=BUYER,
                       json={"price": {"amount": "1", "currency": "USD"}, "supplier_name": "me"}).status_code == 403
    o = new_offer(client, req["id"])
    assert client.post(f"/v1/offers/{o['id']}/accept", headers=SUP_A).status_code == 403
    assert client.post(f"/v1/offers/{o['id']}/accept", headers=SUP_B).status_code == 403
    assert client.post(f"/v1/offers/{o['id']}/withdraw", headers=SUP_B).status_code == 403
    assert client.post(f"/v1/offers/{o['id']}/reject", headers=SUP_A).status_code == 403
    assert client.post(f"/v1/requests/{req['id']}/close", headers=SUP_A).status_code == 403
    assert client.get(f"/v1/requests/{req['id']}/suggestions", headers=SUP_A).status_code == 403
    assert client.get("/v1/requests/req_nope", headers=BUYER).status_code == 404
    assert client.get("/v1/requests", headers=SUP_A).json()["total"] == 0  # "mine" only


def test_invalid_transitions(client):
    req = new_request(client)
    o = new_offer(client, req["id"])
    assert client.post(f"/v1/offers/{o['id']}/accept", headers=BUYER).status_code == 200
    again = client.post(f"/v1/offers/{o['id']}/accept", headers=BUYER)
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_request_transition"
    assert client.post(f"/v1/offers/{o['id']}/withdraw", headers=SUP_A).status_code == 409
    assert client.post(f"/v1/requests/{req['id']}/close", headers=BUYER).status_code == 409
    late = client.post(f"/v1/requests/{req['id']}/offers", headers=SUP_B,
                       json={"price": {"amount": "1", "currency": "USD"}, "supplier_name": "late"})
    assert late.status_code == 409 and late.json()["error"]["details"]["status"] == "awarded"


def test_withdraw_releases_request_and_reject(client):
    req = new_request(client)
    o1, o2 = new_offer(client, req["id"], SUP_A), new_offer(client, req["id"], SUP_B)
    assert client.post(f"/v1/offers/{o1['id']}/withdraw", headers=SUP_A).json()["status"] == "withdrawn"
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] == "negotiating"
    assert client.post(f"/v1/offers/{o2['id']}/reject", headers=BUYER).json()["status"] == "rejected"
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] == "open"
    assert client.post(f"/v1/offers/{o1['id']}/accept", headers=BUYER).status_code == 409


def test_close_rejects_active_offers(client):
    req = new_request(client)
    o = new_offer(client, req["id"])
    assert client.post(f"/v1/requests/{req['id']}/close", headers=BUYER).json()["status"] == "closed"
    assert client.get(f"/v1/requests/{req['id']}/offers", headers=BUYER).json()["items"][0]["status"] == "rejected"
    assert client.post(f"/v1/offers/{o['id']}/accept", headers=BUYER).status_code == 409


def test_deadline_and_offer_validity_expiry(client, clock):
    assert client.post("/v1/requests", headers=BUYER, json={
        "kind": "product", "title": "Past", "quantity": "1", "deadline": "2020-01-01T00:00:00Z"}).status_code == 422
    req = new_request(client, deadline="2026-10-05T00:00:00Z")
    o = new_offer(client, req["id"], valid_until="2026-10-03T00:00:00Z")
    clock.advance(days=3)
    assert client.get(f"/v1/requests/{req['id']}/offers", headers=BUYER).json()["items"][0]["status"] == "expired"
    assert client.post(f"/v1/offers/{o['id']}/accept", headers=BUYER).status_code == 409
    clock.advance(days=3)
    assert client.get(f"/v1/requests/{req['id']}", headers=BUYER).json()["status"] == "expired"
    assert client.get("/v1/requests?status=expired", headers=BUYER).json()["total"] == 1


def test_listing_pagination_filters_and_public_feed(client):
    for i in range(5):
        new_request(client, title=f"Item {i}", kind="raw_material" if i % 2 else "product")
    new_request(client, title="Secret", visibility="private")
    p1 = client.get("/v1/requests?page=1&page_size=4", headers=BUYER).json()
    p2 = client.get("/v1/requests?page=2&page_size=4", headers=BUYER).json()
    assert (p1["total"], len(p1["items"]), len(p2["items"])) == (6, 4, 2)
    assert client.get("/v1/requests?kind=raw_material", headers=BUYER).json()["total"] == 2
    assert client.get("/v1/requests?scope=public", headers=SUP_A).json()["total"] == 5  # no private one
    assert client.get("/v1/requests?scope=public", headers=BUYER).json()["total"] == 0  # not own
    assert client.get("/v1/requests?page_size=500", headers=BUYER).status_code == 422


def test_unsupported_currency(client):
    req = new_request(client)
    r = client.post(f"/v1/requests/{req['id']}/offers", headers=SUP_A,
                    json={"price": {"amount": "1", "currency": "ZZZ"}, "supplier_name": "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_currency"


def test_suggestions_via_mock_sourcing(client):
    req = new_request(client)
    r = client.get(f"/v1/requests/{req['id']}/suggestions?limit=2", headers=BUYER).json()
    assert len(r["items"]) == 2 and r["items"][0]["title"].startswith("LED panel lights")
