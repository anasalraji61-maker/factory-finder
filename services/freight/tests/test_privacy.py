from conftest import NO_LIMITS, make_forwarder, make_quote, make_request, uh

TOK = {"X-Internal-Token": "s3cret"}


def test_internal_routes_404_for_non_internal(make_client):
    c = make_client(internal_token="s3cret", **NO_LIMITS)
    assert c.post("/v1/internal/users/u/export").status_code == 404
    assert c.delete("/v1/internal/users/u/data", headers={"X-Internal-Token": "x"}).status_code == 404


def test_erase_anonymizes_keeps_awarded_history(make_client):
    c = make_client(internal_token="s3cret", **NO_LIMITS)
    h = lambda u: {**uh(u), **TOK}  # noqa: E731
    c.headers.update(TOK)
    make_forwarder(c, "fa")
    awarded = make_request(c, "leaver")
    make_request(c, "leaver", cargo_description="secret open cargo")
    other = make_request(c, "stay")
    q = make_quote(c, awarded["id"], "fa")
    assert c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=h("leaver")).status_code == 200
    exp = c.post("/v1/internal/users/leaver/export", headers=TOK).json()
    assert len(exp["data"]["shipment_requests"]) == 2
    d = c.delete("/v1/internal/users/leaver/data", headers=TOK).json()
    assert d["status"] == "done" and d["counts"]["requests_anonymized"] == 2
    assert sum(c.delete("/v1/internal/users/leaver/data", headers=TOK).json()["counts"].values()) == 0  # idempotent
    # counterparty (forwarder) still sees the awarded request, without the buyer's identity
    won = c.get(f"/v1/freight/requests/{awarded['id']}", headers=h("fa")).json()
    assert won["status"] == "awarded" and "leaver" not in str(won) and won["cargo_description"]
    assert c.post("/v1/internal/users/leaver/export", headers=TOK).json()["data"]["shipment_requests"] == []
    assert c.get(f"/v1/freight/requests/{other['id']}", headers=h("stay")).json()["buyer_id"] == "stay"
