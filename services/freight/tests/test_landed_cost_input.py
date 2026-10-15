import pytest
from conftest import make_forwarder, make_quote, make_request, uh


@pytest.fixture
def awarded(client):
    make_forwarder(client, "fa")
    make_forwarder(client, "fb")
    req = make_request(client)
    qa = make_quote(client, req["id"], "fa", amount="1000")
    qb = make_quote(client, req["id"], "fb", amount="1100")
    return client, req, qa, qb


def url(q):
    return f"/v1/freight/quotes/{q['id']}/landed-cost-input"


def test_owner_gets_exact_override_object(awarded):
    c, req, qa, _ = awarded
    assert c.post(f"/v1/freight/quotes/{qa['id']}/accept", headers=uh("buyer1")).status_code == 200
    r = c.get(url(qa), headers=uh("buyer1"))
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"amount", "currency", "source", "quote_id", "valid_until", "mode_family"}
    assert body["source"] == "forwarder_quote" and body["quote_id"] == qa["id"]
    assert body["amount"] == qa["amount"] and body["currency"] == qa["currency"]
    assert body["valid_until"] == qa["valid_until"] and body["mode_family"] == req["mode"]


def test_not_awarded_quotes_conflict(awarded):
    c, _, qa, qb = awarded
    assert c.get(url(qa), headers=uh("buyer1")).json()["error"]["code"] == "quote_not_awarded"
    c.post(f"/v1/freight/quotes/{qa['id']}/accept", headers=uh("buyer1"))
    r = c.get(url(qb), headers=uh("buyer1"))  # rejected loser
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_not_awarded"


def test_authz_owner_only(awarded):
    c, _, qa, _ = awarded
    c.post(f"/v1/freight/quotes/{qa['id']}/accept", headers=uh("buyer1"))
    assert c.get(url(qa), headers=uh("fa")).status_code == 404  # the quoting forwarder
    assert c.get(url(qa), headers=uh("fb")).status_code == 404  # a losing forwarder
    assert c.get(url(qa), headers=uh("stranger")).status_code == 404
    assert c.get(url(qa)).status_code == 401
    assert c.get("/v1/freight/quotes/qte_nope/landed-cost-input", headers=uh("buyer1")).status_code == 404
