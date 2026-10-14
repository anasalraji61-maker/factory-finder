import pytest
from conftest import ADM, REQ, future, make_forwarder, make_quote, make_request, uh


def post(client, user="buyer1", **over):
    return client.post("/v1/freight/requests", headers=uh(user), json={**REQ, **over})


def test_create_request_shape(client):
    r = make_request(client)
    assert r["status"] == "open" and r["buyer_id"] == "buyer1" and r["outcome"] is None
    assert r["hs_code"] == "690721"  # dots stripped
    assert r["weight_kg"] == "18000.000" and r["volume_cbm"] == "28.500"  # exact decimal strings
    assert r["container_type"] == "40HC" and r["container_count"] == 1 and r["quote_count"] == 0
    assert r["expires_at"].startswith("2026-10-29")  # 14 days default
    assert client.get(f"/v1/freight/requests/{r['id']}", headers=uh("buyer1")).json() == r


@pytest.mark.parametrize(
    "over",
    [
        {"weight_kg": None, "volume_cbm": None},
        {"weight_kg": "0"},
        {"weight_kg": "-5"},
        {"weight_kg": "1.2345"},
        {"mode": "teleport"},
        {"mode": "air", "container_type": "40HC"},
        {"mode": "road", "container_type": "40HC"},
        {"container_type": "99XX"},
        {"container_type": None, "container_count": 2},
        {"container_count": 0},
        {"incoterm": "XXX"},
        {"hs_code": "12"},
        {"hs_code": "abcd"},
        {"currency": "usd"},
        {"origin_country": "china"},
        {"ready_date": "2026-10-14"},  # in the past
        {"ready_date": "2030-01-01"},  # too far
        {"ready_date": "next week"},
        {"quote_deadline_days": 0},
        {"quote_deadline_days": 31},
        {"landed_cost_ref": "bad ref!"},
        {"extra": 1},
        {"buyer_id": "someone"},
    ],
)
def test_request_validation(client, over):
    assert post(client, **over).status_code == 422


def test_valid_variants(client):
    assert post(client, mode="air", container_type=None, container_count=None, weight_kg="450.5", volume_cbm=None, incoterm="CIP").status_code == 201
    assert post(client, mode="rail", container_type="20GP").status_code == 201
    assert post(client, landed_cost_ref="qt_abc123", hs_code=None, ready_date=future(0)).status_code == 201
    assert post(client, mode="sea", container_type="LCL", container_count=None).json()["container_count"] == 1


def test_ready_date_validation_codes(client):
    assert post(client, ready_date="2026-10-14").json()["error"]["code"] == "invalid_ready_date"
    assert post(client, ready_date="garbage").json()["error"]["code"] == "invalid_ready_date"


@pytest.mark.parametrize(
    "over",
    [
        {"cargo_description": "contact me on whatsapp for details"},
        {"cargo_description": "tiles, email boss@tiles.com"},
        {"origin_place": "visit www.port.com"},
        {"cargo_description": "assault rifle spare parts"},
        {"destination_place": "+964 770 123 4567 Baghdad"},
    ],
)
def test_request_screening(client, over):
    r = post(client, **over)
    assert r.status_code == 422 and r.json()["error"]["code"] == "content_rejected"
    assert "boss@tiles" not in r.text and "4567" not in r.text


def test_identity_required_and_not_from_body(client):
    assert client.post("/v1/freight/requests", json=REQ).status_code == 401
    assert client.get("/v1/freight/requests").status_code == 401


def test_open_request_cap(make_client):
    from conftest import NO_LIMITS

    c = make_client(**{**NO_LIMITS, "max_open_requests_per_buyer": 2})
    a = make_request(c)
    make_request(c)
    r = post(c)
    assert r.status_code == 409 and r.json()["error"]["code"] == "request_limit_reached"
    assert post(c, user="other").status_code == 201  # per buyer
    c.post(f"/v1/freight/requests/{a['id']}/close", headers=uh("buyer1"))
    assert post(c).status_code == 201  # closing frees a slot


def test_my_requests_pagination_and_status_filter(client):
    ids = [make_request(client)["id"] for _ in range(5)]
    make_request(client, user="other")
    seen, cur = [], None
    while True:
        r = client.get("/v1/freight/requests", headers=uh("buyer1"), params={"limit": 2, **({"cursor": cur} if cur else {})}).json()
        seen += [i["id"] for i in r["items"]]
        cur = r["next_cursor"]
        if not cur:
            break
    assert seen == ids[::-1]
    client.post(f"/v1/freight/requests/{ids[0]}/close", headers=uh("buyer1"))
    only = client.get("/v1/freight/requests", headers=uh("buyer1"), params={"status": "closed"}).json()["items"]
    assert [i["id"] for i in only] == [ids[0]]
    assert client.get("/v1/freight/requests", headers=uh("buyer1"), params={"status": "bogus"}).status_code == 422
    assert client.get("/v1/freight/requests", headers=uh("buyer1"), params={"limit": 51}).status_code == 422
    assert client.get("/v1/freight/requests", headers=uh("buyer1"), params={"cursor": "x" * 301}).status_code == 422


def test_inbox_matches_lane_mode_incoterm(client):
    f = make_forwarder(client, "fw")  # CN->IQ/AE; sea+air; FOB/CIF/EXW
    match = make_request(client)["id"]
    make_request(client, destination_country="JO")  # lane mismatch
    make_request(client, mode="road", container_type=None, container_count=None)  # mode mismatch
    make_request(client, incoterm="DDP")  # incoterm mismatch
    make_request(client, destination_country="AE", user="b2")  # second match, other buyer
    inbox = client.get("/v1/freight/forwarders/me/inbox", headers=uh("fw")).json()
    assert len(inbox["items"]) == 2 and match in {i["id"] for i in inbox["items"]}
    assert all(i["buyer_id"] is None and i["has_quoted"] is False for i in inbox["items"])
    make_quote(client, match, "fw")
    again = client.get("/v1/freight/forwarders/me/inbox", headers=uh("fw")).json()["items"]
    assert {i["id"]: i["has_quoted"] for i in again}[match] is True
    assert client.get("/v1/freight/forwarders/me/inbox", headers=uh("buyer1")).status_code == 403
    assert f


def test_inbox_wildcard_lanes_and_pagination(client):
    make_forwarder(client, "fw", lanes=[{"origin_country": "*", "destination_country": "*"}])
    for _ in range(4):
        make_request(client, origin_country="TR")
    seen, cur = [], None
    while True:
        r = client.get("/v1/freight/forwarders/me/inbox", headers=uh("fw"), params={"limit": 3, **({"cursor": cur} if cur else {})}).json()
        seen += r["items"]
        cur = r["next_cursor"]
        if not cur:
            break
    assert len(seen) == 4 and len({i["id"] for i in seen}) == 4


def test_inbox_excludes_own_and_non_open(client):
    make_forwarder(client, "fw")
    own = make_request(client, user="fw")
    other = make_request(client, user="b")
    ids = lambda: {i["id"] for i in client.get("/v1/freight/forwarders/me/inbox", headers=uh("fw")).json()["items"]}  # noqa: E731
    assert ids() == {other["id"]}  # own request never shows
    client.post(f"/v1/freight/requests/{other['id']}/close", headers=uh("b"))
    assert ids() == set()
    assert own


def test_request_visibility_by_role(client):
    make_forwarder(client, "fw")
    make_forwarder(client, "fw_jo", lanes=[{"origin_country": "CN", "destination_country": "JO"}])
    r = make_request(client)
    rid = r["id"]
    g = lambda u: client.get(f"/v1/freight/requests/{rid}", headers=uh(u))  # noqa: E731
    assert g("buyer1").json()["buyer_id"] == "buyer1"
    seen = g("fw")
    assert seen.status_code == 200 and seen.json()["buyer_id"] is None and seen.json()["awarded_quote_id"] is None
    assert g("fw_jo").status_code == 404  # lanes do not match
    assert g("random_user").status_code == 404  # not a forwarder, not the owner
    assert client.get("/v1/freight/requests/shp_missing", headers=uh("fw")).status_code == 404


def test_auto_expiry_and_sweep(client, clock):
    make_forwarder(client, "fw")
    r = make_request(client, quote_deadline_days=2)
    q = make_quote(client, r["id"], "fw")
    clock.advance(days=1)
    assert client.get(f"/v1/freight/requests/{r['id']}", headers=uh("buyer1")).json()["status"] == "open"
    clock.advance(days=1, hours=1)
    got = client.get(f"/v1/freight/requests/{r['id']}", headers=uh("buyer1")).json()
    assert got["status"] == "expired" and got["closed_at"]
    # nothing can happen to an expired request
    assert client.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1")).json()["error"]["code"] == "request_expired"
    assert client.post(f"/v1/freight/requests/{r['id']}/close", headers=uh("buyer1")).json()["error"]["code"] == "request_expired"
    assert client.post(f"/v1/freight/requests/{r['id']}/quotes", headers=uh("fw"), json={"amount": "1", "currency": "USD", "transit_days": 3}).status_code == 409
    assert client.get("/v1/freight/forwarders/me/inbox", headers=uh("fw")).json()["items"] == []
    # the sweep endpoint expires in bulk, idempotently
    r2 = make_request(client, quote_deadline_days=1)
    clock.advance(days=2)
    assert client.post("/v1/admin/freight/sweep", headers=ADM).json() == {"expired": 1}
    assert client.post("/v1/admin/freight/sweep", headers=ADM).json() == {"expired": 0}
    assert client.get(f"/v1/freight/requests/{r2['id']}", headers=uh("buyer1")).json()["status"] == "expired"


def test_close_open_is_cancel_and_idempotent(client):
    make_forwarder(client, "fw")
    r = make_request(client)
    q = make_quote(client, r["id"], "fw")
    c1 = client.post(f"/v1/freight/requests/{r['id']}/close", headers=uh("buyer1")).json()
    assert c1["status"] == "closed" and c1["outcome"] == "cancelled" and c1["quote_count"] == 0
    assert client.post(f"/v1/freight/requests/{r['id']}/close", headers=uh("buyer1")).json() == c1
    assert client.get(f"/v1/freight/quotes/{q['id']}", headers=uh("fw")).json()["status"] == "rejected"
    assert client.post(f"/v1/freight/requests/{r['id']}/close", headers=uh("fw")).status_code == 404  # not the owner
