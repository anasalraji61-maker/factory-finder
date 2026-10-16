import json

import httpx
import pytest

P = "http://localhost:8111"
H = {"X-Admin-Token": "adm"}


def _c(make_client, **kw):
    return make_client(admin_token="adm", internal_token="int", payments_admin_token="pay-adm", **kw)


def test_guard_and_injection(make_client, mock_upstream):
    c = _c(make_client)
    route = mock_upstream.route(host="localhost", port=8111, path="/v1/payments/outbox").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    assert c.get("/v1/admin/payments/outbox").status_code == 401
    assert c.get("/v1/admin/payments/outbox", headers={"X-Admin-Token": "bad"}).status_code == 401
    assert not route.called
    r = c.get("/v1/admin/payments/outbox?status=dead&limit=500&cursor=abc", headers={**H, "X-User-Id": "evil", "Authorization": "Bearer x"})
    assert r.status_code == 200
    req = route.calls.last.request
    h = req.headers
    assert h["x-admin-token"] == "pay-adm" and h["x-internal-token"] == "int" and h["x-user-id"] == "admin"
    assert "authorization" not in h
    q = dict(req.url.params)
    assert q == {"status": "dead", "page_size": "100", "cursor": "abc"}


def test_disabled_without_tokens(make_client):
    c = make_client(internal_token="int", payments_admin_token="p")
    assert c.get("/v1/admin/payments/outbox", headers=H).status_code == 404  # no gateway admin token
    c = make_client(admin_token="adm")
    assert c.get("/v1/admin/payments/outbox", headers=H).status_code == 404  # no payments token
    assert c.post("/v1/admin/payments/outbox/e1/requeue", headers=H).status_code == 404


@pytest.mark.parametrize("qs", ["foo=1", "status=bogus", "limit=abc", "limit=0", "cursor=a%20b", "status=dead&x=1"])
def test_bad_query_rejected(make_client, mock_upstream, qs):
    c = _c(make_client)
    route = mock_upstream.route(host="localhost", port=8111).mock(return_value=httpx.Response(200, json={}))
    assert c.get(f"/v1/admin/payments/outbox?{qs}", headers=H).status_code == 422
    assert not route.called


def test_requeue(make_client, mock_upstream):
    c = _c(make_client)
    route = mock_upstream.route(host="localhost", port=8111, path="/v1/payments/outbox/e-1/requeue").mock(
        return_value=httpx.Response(409, json={"error": {"code": "not_dead"}})
    )
    assert c.post("/v1/admin/payments/outbox/e-1/requeue").status_code == 401
    assert not route.called
    r = c.post("/v1/admin/payments/outbox/e-1/requeue", headers={**H, "X-User-Id": "evil"}, json={"a": 1})
    assert r.status_code == 409  # upstream status passes through
    req = route.calls.last.request
    assert req.headers["x-admin-token"] == "pay-adm" and req.headers["x-user-id"] == "admin"
    assert req.content == b""
    assert c.post("/v1/admin/payments/outbox/e-1/requeue?x=1", headers=H).status_code == 422


@pytest.mark.parametrize("bad", ["..", "%2e%2e", "a%2Fb", "a b", "x" * 65, "a.b"])
def test_requeue_bad_id(make_client, mock_upstream, bad):
    c = _c(make_client)
    route = mock_upstream.route(host="localhost", port=8111).mock(return_value=httpx.Response(200, json={}))
    assert c.post(f"/v1/admin/payments/outbox/{bad}/requeue", headers=H).status_code in (404, 400)
    assert not route.called


def test_only_allowlisted_methods(make_client):
    c = _c(make_client)
    assert c.delete("/v1/admin/payments/outbox", headers=H).status_code in (404, 405)
    assert c.get("/v1/admin/payments/other", headers=H).status_code in (404, 405)


def test_review_list(make_client, mock_upstream, caplog):
    c = _c(make_client)
    body = {"items": [{"id": "i1"}], "total": 1, "page": 1, "page_size": 100}
    route = mock_upstream.route(host="localhost", port=8111, path="/v1/payments/review").mock(
        return_value=httpx.Response(200, json=body)
    )
    assert c.get("/v1/admin/payments/review").status_code == 401
    assert not route.called
    with caplog.at_level("INFO", logger="ff_gateway.admin"):
        r = c.get("/v1/admin/payments/review?limit=500&cursor=abc", headers={**H, "X-Reviewer": "bob@x.com", "X-User-Id": "evil"})
    assert r.status_code == 200 and r.json() == body
    h = route.calls.last.request.headers
    assert h["x-admin-token"] == "pay-adm" and h["x-internal-token"] == "int" and h["x-user-id"] == "admin"
    assert h["x-reviewer"] == "bobx.com"
    assert dict(route.calls.last.request.url.params) == {"page_size": "100", "cursor": "abc"}
    assert "payments_review_list reviewer=bobx.com" in caplog.text


@pytest.mark.parametrize("qs", ["status=dead", "foo=1", "limit=0"])
def test_review_bad_query(make_client, mock_upstream, qs):
    c = _c(make_client)
    route = mock_upstream.route(host="localhost", port=8111).mock(return_value=httpx.Response(200, json={}))
    assert c.get(f"/v1/admin/payments/review?{qs}", headers=H).status_code == 422
    assert not route.called


def test_review_disabled_and_down(make_client, mock_upstream):
    assert make_client(admin_token="adm").get("/v1/admin/payments/review", headers=H).status_code == 404
    c = _c(make_client)
    mock_upstream.route(host="localhost", port=8111, path="/v1/payments/review").mock(side_effect=httpx.ConnectError("x"))
    assert c.get("/v1/admin/payments/review", headers=H).status_code == 502
    mock_upstream.route(host="localhost", port=8111, path="/v1/payments/review").mock(side_effect=httpx.ReadTimeout("x"))
    assert c.get("/v1/admin/payments/review", headers=H).status_code == 504


RES = "/v1/admin/payments/review/inv_1/resolve"
RES_UP = "/v1/payments/review/inv_1/resolve"


def test_review_resolve_forwards_clean_body_and_audits(make_client, mock_upstream, caplog):
    c = _c(make_client)
    out = {"id": "rvw_1", "action": "settle"}
    route = mock_upstream.route(host="localhost", port=8111, path=RES_UP).mock(return_value=httpx.Response(200, json=out))
    body = {"action": "settle", "note": "ok", "confirm_amount_mismatch": True,
            "received_amount": {"amount": "9.50", "currency": "USD"}}
    assert c.post(RES, json=body).status_code == 401
    assert not route.called
    with caplog.at_level("INFO", logger="ff_gateway.admin"):
        r = c.post(RES, json=body, headers={**H, "X-Reviewer": "bob@x.com", "X-User-Id": "evil"})
    assert r.status_code == 200 and r.json() == out
    req = route.calls.last.request
    assert req.headers["x-admin-token"] == "pay-adm" and req.headers["x-internal-token"] == "int"
    assert req.headers["x-user-id"] == "admin" and req.headers["x-reviewer"] == "bobx.com"
    assert json.loads(req.content) == body
    assert "payments_review_resolve reviewer=bobx.com invoice=inv_1 resolution=settle" in caplog.text


def test_review_resolve_upstream_status_passthrough(make_client, mock_upstream):
    c = _c(make_client)
    mock_upstream.route(host="localhost", port=8111, path=RES_UP).mock(
        return_value=httpx.Response(409, json={"error": {"code": "already_resolved"}}))
    r = c.post(RES, json={"action": "dismiss"}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_resolved"


@pytest.mark.parametrize("bad", [
    {}, {"action": "nuke"}, {"action": "dismiss", "x": 1}, {"action": "dismiss", "note": "x" * 501},
    {"action": "dismiss", "note": 5}, {"action": "settle", "confirm_amount_mismatch": "true"},
    {"action": "settle", "received_amount": {"amount": 9.5, "currency": "USD"}},
    {"action": "settle", "received_amount": {"amount": "9.5", "currency": "USD", "x": 1}},
    {"action": "settle", "received_amount": "9.5"}, [], "dismiss",
])
def test_review_resolve_bad_body(make_client, mock_upstream, bad):
    c = _c(make_client)
    route = mock_upstream.route(host="localhost", port=8111).mock(return_value=httpx.Response(200, json={}))
    assert c.post(RES, json=bad, headers=H).status_code == 422
    assert not route.called


def test_review_resolve_misc_guards(make_client, mock_upstream):
    c = _c(make_client)
    route = mock_upstream.route(host="localhost", port=8111).mock(return_value=httpx.Response(200, json={}))
    assert c.post(RES, content=b"{nope", headers={**H, "Content-Type": "application/json"}).status_code == 422
    assert c.post(RES + "?x=1", json={"action": "dismiss"}, headers=H).status_code == 422
    big = {"action": "dismiss", "note": "a" * 5000}
    assert c.post(RES, json=big, headers=H).status_code == 413
    for bad in ["..", "%2e%2e", "a%2Fb", "a b", "x" * 65]:
        assert c.post(f"/v1/admin/payments/review/{bad}/resolve", json={"action": "dismiss"}, headers=H).status_code in (404, 400)
    assert c.get(RES, headers=H).status_code in (404, 405)
    assert not route.called


def test_review_resolve_disabled_and_down(make_client, mock_upstream):
    assert make_client(admin_token="adm").post(RES, json={"action": "dismiss"}, headers=H).status_code == 404
    c = _c(make_client)
    mock_upstream.route(host="localhost", port=8111, path=RES_UP).mock(side_effect=httpx.ConnectError("x"))
    assert c.post(RES, json={"action": "dismiss"}, headers=H).status_code == 502
    mock_upstream.route(host="localhost", port=8111, path=RES_UP).mock(side_effect=httpx.ReadTimeout("x"))
    assert c.post(RES, json={"action": "dismiss"}, headers=H).status_code == 504
