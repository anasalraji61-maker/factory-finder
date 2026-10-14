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
