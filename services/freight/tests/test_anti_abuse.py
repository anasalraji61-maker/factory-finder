"""security-review-2026-10-d items 2 (rating farming) and 3 (report-abuse auto-hide)."""

from conftest import make_forwarder, make_quote, make_request, uh

REP = {"reason": "spam"}


def _closed(c, buyer="buyer1", fw="fw"):
    req = make_request(c, buyer)
    q = make_quote(c, req["id"], fw)
    assert c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh(buyer)).status_code == 200
    assert c.post(f"/v1/freight/requests/{req['id']}/close", headers=uh(buyer)).status_code == 200
    return req["id"]


def _rate(c, rid, buyer="buyer1"):
    return c.post(f"/v1/freight/requests/{rid}/rating", headers=uh(buyer), json={"stars": 5})


def test_rating_waits_after_close(make_client, clock):
    c = make_client(admin_token="adm-secret", rate_requests=0, rate_quotes=0, rate_applications=0, rate_ratings=0, rating_min_delay_seconds=3600)
    make_forwarder(c, "fw")
    rid = _closed(c)
    r = _rate(c, rid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "rating_too_early"
    clock.advance(seconds=3601)
    assert _rate(c, rid).status_code == 201


def test_rating_pair_limit(make_client):
    c = make_client(admin_token="adm-secret", rate_requests=0, rate_quotes=0, rate_applications=0, rate_ratings=0, rating_min_delay_seconds=0, rating_max_per_pair=2)
    make_forwarder(c, "fw")
    ids = [_closed(c) for _ in range(3)]
    assert [_rate(c, i).status_code for i in ids] == [201, 201, 409]
    assert _rate(c, ids[2]).json()["error"]["code"] == "rating_pair_limit"
    other = _closed(c, "buyer2")  # another buyer is unaffected
    assert _rate(c, other, "buyer2").status_code == 201


def test_new_accounts_cannot_auto_hide(make_client, clock):
    c = make_client(admin_token="adm-secret", report_hide_threshold=2, report_min_account_age_seconds=3600, rate_requests=0, rate_reports=0, rate_quotes=0, rate_applications=0)
    for u in ("f1", "f2"):
        make_forwarder(c, u)
    rid = make_request(c)["id"]
    for u in ("f1", "f2"):
        assert c.post(f"/v1/freight/requests/{rid}/report", headers=uh(u), json=REP).status_code == 202
    assert c.get(f"/v1/freight/requests/{rid}", headers=uh("buyer1")).status_code == 200  # still visible, reports recorded
    assert c.get("/v1/admin/freight/requests", params={"visibility": "visible"}, headers={"X-Admin-Token": "adm-secret"}).json()["items"][0]["report_count"] == 2
    clock.advance(seconds=3601)
    make_forwarder(c, "f3")  # fresh account: does not count
    assert c.post(f"/v1/freight/requests/{rid}/report", headers=uh("f3"), json=REP).status_code == 202
    assert c.get(f"/v1/freight/requests/{rid}", headers=uh("buyer1")).status_code == 404  # two aged reporters reached the threshold


def test_awarded_request_is_not_auto_hidden(make_client):
    c = make_client(admin_token="adm-secret", report_hide_threshold=1, report_min_account_age_seconds=0, rate_requests=0, rate_reports=0, rate_quotes=0, rate_applications=0)
    make_forwarder(c, "fw")
    make_forwarder(c, "f2")
    req = make_request(c)
    q = make_quote(c, req["id"], "fw")
    c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1"))
    c.post(f"/v1/freight/requests/{req['id']}/report", headers=uh("fw"), json=REP)  # winner cannot sink the deal; others cannot see it
    assert c.get(f"/v1/freight/requests/{req['id']}", headers=uh("buyer1")).status_code == 200
