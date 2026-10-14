import pytest
from conftest import ADM, make_forwarder, make_quote, make_request, uh


@pytest.fixture
def two(client):
    make_forwarder(client, "fa")
    make_forwarder(client, "fb")
    req = make_request(client)
    qa = make_quote(client, req["id"], "fa", amount="1000")
    qb = make_quote(client, req["id"], "fb", amount="1100")
    return client, req, qa, qb


def acc(c, q, user="buyer1"):
    return c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh(user))


def test_accept_awards_and_rejects_others(two):
    c, req, qa, qb = two
    r = acc(c, qa)
    assert r.status_code == 200
    body = r.json()
    assert body["request"]["status"] == "awarded" and body["request"]["awarded_quote_id"] == qa["id"]
    assert body["request"]["awarded_at"] and body["request"]["quote_count"] == 1
    assert body["quote"]["status"] == "accepted"
    assert c.get(f"/v1/freight/quotes/{qb['id']}", headers=uh("buyer1")).json()["status"] == "rejected"
    # the winner sees the buyer; the loser does not
    won = c.get(f"/v1/freight/requests/{req['id']}", headers=uh("fa")).json()
    lost = c.get(f"/v1/freight/requests/{req['id']}", headers=uh("fb")).json()
    assert won["buyer_id"] == "buyer1" and won["awarded_quote_id"] == qa["id"]
    assert lost["buyer_id"] is None and lost["awarded_quote_id"] is None and lost["status"] == "awarded"


def test_accept_is_idempotent(two):
    c, req, qa, _ = two
    first = acc(c, qa).json()
    for _ in range(3):
        again = acc(c, qa)
        assert again.status_code == 200 and again.json() == first
    assert c.get(f"/v1/freight/requests/{req['id']}", headers=uh("buyer1")).json()["awarded_at"] == first["request"]["awarded_at"]


def test_accept_other_quote_after_award_conflicts(two):
    c, _, qa, qb = two
    acc(c, qa)
    r = acc(c, qb)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_awarded"
    c.post(f"/v1/freight/requests/{qa['request_id']}/close", headers=uh("buyer1"))
    assert acc(c, qb).json()["error"]["code"] == "already_awarded"  # still, after completion
    assert acc(c, qa).status_code == 200  # and the winner stays idempotent


def test_accept_access_control(two):
    c, _, qa, _ = two
    assert acc(c, qa, "fa").status_code == 404  # the forwarder cannot accept its own quote
    assert acc(c, qa, "stranger").status_code == 404
    assert c.post("/v1/freight/quotes/qte_nope/accept", headers=uh("buyer1")).status_code == 404
    assert c.post(f"/v1/freight/quotes/{qa['id']}/accept").status_code == 401


def test_accept_on_closed_without_award(two):
    c, req, qa, _ = two
    c.post(f"/v1/freight/requests/{req['id']}/close", headers=uh("buyer1"))
    r = acc(c, qa)
    assert r.status_code == 409 and r.json()["error"]["code"] in ("request_not_open", "quote_not_available")


def test_no_changes_to_quotes_after_award(two):
    c, _, qa, qb = two
    acc(c, qa)
    from conftest import QUOTE

    assert c.put(f"/v1/freight/quotes/{qa['id']}", headers=uh("fa"), json=QUOTE).json()["error"]["code"] == "quote_final"
    assert c.put(f"/v1/freight/quotes/{qb['id']}", headers=uh("fb"), json=QUOTE).json()["error"]["code"] == "quote_final"
    assert c.post(f"/v1/freight/quotes/{qa['id']}/withdraw", headers=uh("fa")).json()["error"]["code"] == "quote_final"
    r = c.post(f"/v1/freight/requests/{qa['request_id']}/quotes", headers=uh("fb"), json=QUOTE)
    assert r.status_code == 409  # request no longer open


def test_state_machine_transitions(client, clock):
    make_forwarder(client, "fw")
    req = make_request(client, quote_deadline_days=3)
    q = make_quote(client, req["id"], "fw")
    state = lambda: client.get(f"/v1/freight/requests/{req['id']}", headers=uh("buyer1")).json()  # noqa: E731
    assert state()["status"] == "open"
    acc(client, q)
    assert state()["status"] == "awarded"
    clock.advance(days=10)  # an awarded request never expires
    assert state()["status"] == "awarded"
    done = client.post(f"/v1/freight/requests/{req['id']}/close", headers=uh("buyer1")).json()
    assert done["status"] == "closed" and done["outcome"] == "completed"
    assert client.get("/v1/freight/forwarders/me", headers=uh("fw")).json()["completed_jobs"] == 1
    client.post(f"/v1/freight/requests/{req['id']}/close", headers=uh("buyer1"))  # idempotent: no double count
    assert client.get("/v1/freight/forwarders/me", headers=uh("fw")).json()["completed_jobs"] == 1


def _completed(client, buyer="buyer1", fw="fw"):
    req = make_request(client, user=buyer)
    q = make_quote(client, req["id"], fw)
    acc(client, q, buyer)
    client.post(f"/v1/freight/requests/{req['id']}/close", headers=uh(buyer))
    return req


def test_rating_flow(client):
    fid = make_forwarder(client, "fw")
    req = make_request(client)
    q = make_quote(client, req["id"], "fw")
    rate = lambda stars=5, user="buyer1", **kw: client.post(  # noqa: E731
        f"/v1/freight/requests/{req['id']}/rating", headers=uh(user), json={"stars": stars, **kw}
    )
    assert rate().json()["error"]["code"] == "not_completed"  # still open
    acc(client, q)
    assert rate().json()["error"]["code"] == "not_completed"  # awarded, not finished
    client.post(f"/v1/freight/requests/{req['id']}/close", headers=uh("buyer1"))
    assert rate(user="fw").status_code == 404 and rate(user="stranger").status_code == 404
    assert rate(0).status_code == 422 and rate(6).status_code == 422 and rate(3, extra=1).status_code == 422
    assert rate(5, comment="mail me at x@y.com").json()["error"]["code"] == "content_rejected"
    ok = rate(4, comment="Good communication")
    assert ok.status_code == 201
    assert ok.json()["stars"] == 4 and ok.json()["forwarder_id"] == fid and "buyer_id" not in ok.json()
    assert rate(5).status_code == 409 and rate(5).json()["error"]["code"] == "already_rated"
    prof = client.get(f"/v1/freight/forwarders/{fid}", headers=uh("x")).json()
    assert prof["rating"] == {"average": "4.00", "count": 1} and prof["completed_jobs"] == 1
    page = client.get(f"/v1/freight/forwarders/{fid}/ratings", headers=uh("x")).json()
    assert [i["stars"] for i in page["items"]] == [4] and page["items"][0]["comment"] == "Good communication"


def test_rating_cancelled_request_not_ratable_and_average(client):
    fid = make_forwarder(client, "fw")
    cancelled = make_request(client)
    client.post(f"/v1/freight/requests/{cancelled['id']}/close", headers=uh("buyer1"))
    r = client.post(f"/v1/freight/requests/{cancelled['id']}/rating", headers=uh("buyer1"), json={"stars": 5})
    assert r.json()["error"]["code"] == "not_completed"
    stars = [5, 4, 4]
    for i, s in enumerate(stars):
        req = _completed(client, buyer=f"b{i}")
        client.post(f"/v1/freight/requests/{req['id']}/rating", headers=uh(f"b{i}"), json={"stars": s})
    assert client.get(f"/v1/freight/forwarders/{fid}", headers=uh("x")).json()["rating"] == {"average": "4.33", "count": 3}
    seen, cur = [], None
    while True:
        r = client.get(f"/v1/freight/forwarders/{fid}/ratings", headers=uh("x"), params={"limit": 2, **({"cursor": cur} if cur else {})}).json()
        seen += [i["stars"] for i in r["items"]]
        cur = r["next_cursor"]
        if not cur:
            break
    assert seen == [4, 4, 5]
    assert client.get("/v1/freight/forwarders/fwd_nope/ratings", headers=uh("x")).status_code == 404
    assert ADM


def test_accept_concurrent_race_only_one_winner(client):
    """Conditional UPDATE: two different quotes accepted back-to-back, only the first wins."""
    make_forwarder(client, "fa")
    make_forwarder(client, "fb")
    req = make_request(client)
    qa = make_quote(client, req["id"], "fa")
    qb = make_quote(client, req["id"], "fb")
    codes = sorted([acc(client, qa).status_code, acc(client, qb).status_code])
    assert codes == [200, 409]
