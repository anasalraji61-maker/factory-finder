from conftest import ADM, make_forwarder, make_quote, make_request, uh

REP = {"reason": "scam_or_fraud", "details": "asked me to pay outside, mail a@b.com"}


def test_admin_disabled_without_token_is_404(make_client):
    c = make_client()  # no admin token
    for path in ("applications", "forwarders", "requests", "quotes", "reports"):
        assert c.get(f"/v1/admin/freight/{path}", headers=ADM).status_code == 404, path
    assert c.post("/v1/admin/freight/applications/app_x/approve", headers=ADM).status_code == 404
    assert c.post("/v1/admin/freight/applications/app_x/reject", headers=ADM, json={"reason": "abc"}).status_code == 404
    assert c.post("/v1/admin/freight/forwarders/fwd_x/suspend", headers=ADM, json={"reason": "abc"}).status_code == 404
    assert c.post("/v1/admin/freight/requests/shp_x/hide", headers=ADM, json={"reason": "abc"}).status_code == 404
    assert c.post("/v1/admin/freight/quotes/qte_x/restore", headers=ADM).status_code == 404
    assert c.post("/v1/admin/freight/sweep", headers=ADM).status_code == 404


def test_admin_requires_correct_token(client):
    assert client.get("/v1/admin/freight/applications").status_code == 401
    assert client.get("/v1/admin/freight/applications", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert client.get("/v1/admin/freight/applications", headers=uh()).status_code == 401  # identity alone is not enough
    assert client.get("/v1/admin/freight/applications", headers={"X-Admin-Token": "adm-secret"}).status_code == 200
    assert client.get("/v1/admin/freight/applications?status=bogus", headers=ADM).status_code == 422


def test_request_auto_hidden_at_threshold(make_client):
    c = make_client(admin_token="adm-secret", report_min_account_age_seconds=0, report_hide_threshold=2, rate_requests=0, rate_reports=0, rate_quotes=0, rate_applications=0)
    for u in ("f1", "f2", "f3"):
        make_forwarder(c, u)
    req = make_request(c)
    rid = req["id"]
    r = c.post(f"/v1/freight/requests/{rid}/report", headers=uh("f1"), json=REP)
    assert r.status_code == 202 and r.json() == {"status": "received"}
    assert c.post(f"/v1/freight/requests/{rid}/report", headers=uh("f1"), json=REP).status_code == 202  # repeat counts once
    assert c.get(f"/v1/freight/requests/{rid}", headers=uh("f2")).status_code == 200
    c.post(f"/v1/freight/requests/{rid}/report", headers=uh("f2"), json={"reason": "spam"})
    for u in ("buyer1", "f3", "f1"):
        assert c.get(f"/v1/freight/requests/{rid}", headers=uh(u)).status_code == 404
    assert c.get("/v1/freight/requests", headers=uh("buyer1")).json()["items"] == []
    assert c.get("/v1/freight/forwarders/me/inbox", headers=uh("f3")).json()["items"] == []
    assert c.post(f"/v1/freight/requests/{rid}/quotes", headers=uh("f3"), json={"amount": "1", "currency": "USD", "transit_days": 3}).status_code == 404
    reps = c.get("/v1/admin/freight/reports", params={"target_id": rid}, headers=ADM).json()["items"]
    assert len(reps) == 2 and "a@b.com" not in str(reps)  # details are redacted
    adm = c.get("/v1/admin/freight/requests", params={"visibility": "hidden"}, headers=ADM).json()["items"]
    assert [i["id"] for i in adm] == [rid] and adm[0]["report_count"] == 2 and adm[0]["hidden_reason"].startswith("auto")
    restored = c.post(f"/v1/admin/freight/requests/{rid}/restore", headers=ADM).json()
    assert restored["visibility"] == "visible" and restored["report_count"] == 0
    assert c.get(f"/v1/freight/requests/{rid}", headers=uh("buyer1")).status_code == 200
    c.post(f"/v1/freight/requests/{rid}/report", headers=uh("f1"), json={"reason": "spam"})
    assert c.get(f"/v1/freight/requests/{rid}", headers=uh("buyer1")).status_code == 200  # old reports were cleared


def test_report_rules(client):
    make_forwarder(client, "fw")
    make_forwarder(client, "jo", lanes=[{"origin_country": "CN", "destination_country": "JO"}])
    req = make_request(client)
    rp = lambda target, user, body=None: client.post(target, headers=uh(user), json=body or {"reason": "spam"})  # noqa: E731
    base = f"/v1/freight/requests/{req['id']}/report"
    assert rp(base, "buyer1").json()["error"]["code"] == "cannot_report_own"
    assert rp(base, "jo").status_code == 404  # cannot see it, so cannot report it
    assert rp(base, "stranger").status_code == 404
    assert rp(base, "fw", {"reason": "nonsense"}).status_code == 422
    assert rp(base, "fw", {"reason": "spam", "extra": 1}).status_code == 422
    assert rp(base, "fw").status_code == 202
    assert rp("/v1/freight/requests/shp_nope/report", "fw").status_code == 404


def test_report_quote_and_hide_excludes_from_comparison(make_client):
    c = make_client(admin_token="adm-secret", report_min_account_age_seconds=0, report_hide_threshold=1, rate_requests=0, rate_reports=0, rate_quotes=0, rate_applications=0)
    make_forwarder(c, "fw")
    req = make_request(c)
    q = make_quote(c, req["id"], "fw")
    base = f"/v1/freight/quotes/{q['id']}/report"
    assert c.post(base, headers=uh("fw"), json={"reason": "spam"}).status_code == 404  # only the buyer may report a quote
    assert c.post(base, headers=uh("stranger"), json={"reason": "spam"}).status_code == 404
    assert c.post(base, headers=uh("buyer1"), json={"reason": "misleading"}).status_code == 202
    assert c.get(f"/v1/freight/quotes/{q['id']}", headers=uh("buyer1")).status_code == 404
    assert c.get(f"/v1/freight/requests/{req['id']}/quotes", headers=uh("buyer1")).json()["items"] == []
    assert c.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1")).json()["items"] == []
    assert c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1")).status_code == 404
    hidden = c.get("/v1/admin/freight/quotes", params={"visibility": "hidden"}, headers=ADM).json()["items"]
    assert [i["id"] for i in hidden] == [q["id"]] and hidden[0]["report_count"] == 1
    assert c.post(f"/v1/admin/freight/quotes/{q['id']}/restore", headers=ADM).json()["visibility"] == "visible"
    assert len(c.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1")).json()["items"]) == 1
    h = c.post(f"/v1/admin/freight/quotes/{q['id']}/hide", headers=ADM, json={"reason": "abusive terms"}).json()
    assert h["hidden_reason"] == "admin: abusive terms"
    assert c.post(f"/v1/admin/freight/quotes/{q['id']}/hide", headers=ADM, json={"reason": "x"}).status_code == 422
    assert c.post("/v1/admin/freight/quotes/qte_nope/hide", headers=ADM, json={"reason": "abc"}).status_code == 404
    assert c.get("/v1/admin/freight/quotes", params={"request_id": req["id"]}, headers=ADM).json()["items"]


def test_report_forwarder_requires_dealings_and_never_auto_actions(make_client):
    c = make_client(admin_token="adm-secret", report_min_account_age_seconds=0, report_hide_threshold=1, rate_requests=0, rate_reports=0, rate_quotes=0, rate_applications=0)
    fid = make_forwarder(c, "fw")
    path = f"/v1/freight/forwarders/{fid}/report"
    assert c.post(path, headers=uh("buyer1"), json={"reason": "scam_or_fraud"}).status_code == 404  # never dealt with it
    assert c.post(path, headers=uh("fw"), json={"reason": "spam"}).json()["error"]["code"] == "cannot_report_own"
    req = make_request(c)
    make_quote(c, req["id"], "fw")
    assert c.post(path, headers=uh("buyer1"), json={"reason": "scam_or_fraud"}).status_code == 202
    assert c.get(f"/v1/freight/forwarders/{fid}", headers=uh("x")).status_code == 200  # still active: admins decide
    reps = c.get("/v1/admin/freight/reports", params={"target_type": "forwarder"}, headers=ADM).json()["items"]
    assert reps[0]["target_id"] == fid
    assert c.get("/v1/admin/freight/reports", params={"target_type": "nonsense"}, headers=ADM).status_code == 422


def test_admin_request_moderation_and_filters(client):
    make_forwarder(client, "fw")
    a = make_request(client)
    b = make_request(client)
    client.post(f"/v1/freight/requests/{b['id']}/close", headers=uh("buyer1"))
    h = client.post(f"/v1/admin/freight/requests/{a['id']}/hide", headers=ADM, json={"reason": "duplicate listing"}).json()
    assert h["visibility"] == "hidden" and h["buyer_id"] == "buyer1" and h["hidden_reason"] == "admin: duplicate listing"
    assert client.get(f"/v1/freight/requests/{a['id']}", headers=uh("buyer1")).status_code == 404
    ids = lambda **q: [i["id"] for i in client.get("/v1/admin/freight/requests", params=q, headers=ADM).json()["items"]]  # noqa: E731
    assert ids(visibility="hidden") == [a["id"]] and ids(status="closed") == [b["id"]] and set(ids()) == {a["id"], b["id"]}
    assert client.get("/v1/admin/freight/requests?status=nope", headers=ADM).status_code == 422
    assert client.post("/v1/admin/freight/requests/shp_nope/restore", headers=ADM).status_code == 404


def test_rate_limits(make_client):
    c = make_client(rate_requests=2, rate_quotes=1, rate_applications=1, rate_ratings=1, rate_reports=1, admin_token="adm-secret")
    from conftest import APP, REQ

    assert c.post("/v1/freight/applications", headers=uh("u1"), json=APP).status_code == 201
    first = c.get("/v1/admin/freight/applications", headers=ADM).json()["items"][0]["id"]
    c.post(f"/v1/admin/freight/applications/{first}/reject", headers=ADM, json={"reason": "incomplete"})
    a2 = c.post("/v1/freight/applications", headers=uh("u1"), json=APP)
    assert a2.status_code == 429 and int(a2.headers["Retry-After"]) >= 1
    assert a2.json()["error"]["code"] == "rate_limited" and a2.json()["error"]["details"]["action"] == "applications"
    c.post("/v1/freight/requests", headers=uh("b"), json=REQ)
    c.post("/v1/freight/requests", headers=uh("b"), json=REQ)
    r = c.post("/v1/freight/requests", headers=uh("b"), json=REQ)
    assert r.status_code == 429
    assert c.post("/v1/freight/requests", headers=uh("other"), json=REQ).status_code == 201  # per user
    # rejected (screened) attempts count too
    bad = {**REQ, "cargo_description": "mail me boss@x.com"}
    assert c.post("/v1/freight/requests", headers=uh("probe"), json=bad).status_code == 422
    assert c.post("/v1/freight/requests", headers=uh("probe"), json=bad).status_code == 422
    assert c.post("/v1/freight/requests", headers=uh("probe"), json=bad).status_code == 429


def test_rate_window_slides(make_client, clock):
    c = make_client(rate_requests=1, rate_window_seconds=60)
    from conftest import REQ

    assert c.post("/v1/freight/requests", headers=uh("b"), json=REQ).status_code == 201
    assert c.post("/v1/freight/requests", headers=uh("b"), json=REQ).status_code == 429
    clock.advance(seconds=61)
    assert c.post("/v1/freight/requests", headers=uh("b"), json=REQ).status_code == 201
