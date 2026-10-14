import base64
import json

from conftest import make_forwarder, make_quote, make_request, uh


def _cur(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode()


def test_accept_with_stale_revision_is_refused(client):
    """Bait-and-switch: the forwarder revises the price after the buyer looked at it."""
    make_forwarder(client, "fa")
    req = make_request(client)
    q = make_quote(client, req["id"], "fa", amount="1000")
    assert q["revision"] == 1
    r = client.put(f"/v1/freight/quotes/{q['id']}", headers=uh("fa"), json={
        "amount": "5000", "currency": q["currency"], "transit_days": 20})
    assert r.status_code == 200 and r.json()["revision"] == 2
    stale = client.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1"), json={"revision": 1})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "quote_changed"
    assert client.get(f"/v1/freight/requests/{req['id']}", headers=uh("buyer1")).json()["status"] == "open"
    ok = client.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1"), json={"revision": 2})
    assert ok.status_code == 200 and ok.json()["quote"]["amount"] == "5000.00"


def test_accept_without_body_still_works(client):
    make_forwarder(client, "fa")
    req = make_request(client)
    q = make_quote(client, req["id"], "fa")
    assert client.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1")).status_code == 200


def test_hostile_cursors_are_422_not_500(client):
    for d in (
        {"k": "c", "t": "0001-01-01T00:00:00+05:00", "i": "a"},
        {"k": "c", "t": "9999-12-31T23:59:59-05:00", "i": "a"},
    ):
        r = client.get("/v1/freight/requests", headers=uh(), params={"cursor": _cur(d)})
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_cursor"


def test_freight_email_screen_anchored():
    import time

    from ff_freight.moderation import contact_kinds

    assert "contact_email" in contact_kinds("john.doe@example.com")
    t = time.perf_counter()
    contact_kinds("a" * 2200)
    assert time.perf_counter() - t < 0.2
