import httpx
import pytest

A = {"X-Admin-Token": "adm-secret"}
D = "http://localhost:8110"


@pytest.fixture
def admin(make_client):
    return make_client(admin_token="adm-secret", internal_token="int-secret", admin_fail_limit_per_minute=1000)


CASES = [
    ("get", "/v1/admin/demand/signals", "/v1/signals"),
    ("post", "/v1/admin/demand/signals", "/v1/signals"),
    ("post", "/v1/admin/demand/signals/poll", "/v1/signals/poll"),
    ("get", "/v1/admin/demand/signals/sig_1", "/v1/signals/sig_1"),
    ("get", "/v1/admin/demand/drafts", "/v1/drafts"),
    ("get", "/v1/admin/demand/drafts/d1", "/v1/drafts/d1"),
    ("post", "/v1/admin/demand/drafts/d1/approve", "/v1/drafts/d1/approve"),
    ("post", "/v1/admin/demand/drafts/d1/reject", "/v1/drafts/d1/reject"),
    ("post", "/v1/admin/demand/drafts/d1/mark-published", "/v1/drafts/d1/mark-published"),
    ("post", "/v1/admin/demand/drafts/d1/outcome", "/v1/drafts/d1/outcome"),
    ("get", "/v1/admin/demand/quota", "/v1/quota"),
]


def test_disabled_without_token(client, mock_upstream):
    route = mock_upstream.route(host="localhost", port=8110).mock(
        return_value=httpx.Response(200, json={})
    )
    for m, p, _ in CASES + [("get", "/v1/admin/overview", "")]:
        assert getattr(client, m)(p, headers={"X-Admin-Token": "x"}).status_code == 404
    assert not route.called


def test_wrong_token_401(admin, mock_upstream, hdr):
    route = mock_upstream.route(host="localhost", port=8110).mock(
        return_value=httpx.Response(200, json={})
    )
    for m, p, _ in CASES + [("get", "/v1/admin/overview", "")]:
        for h in ({}, {"X-Admin-Token": "wrong"}, hdr):
            assert getattr(admin, m)(p, headers=h).status_code == 401
    assert not route.called


@pytest.mark.parametrize(("method", "path", "up"), CASES)
def test_forwarding(admin, mock_upstream, method, path, up):
    route = mock_upstream.route(host="localhost", port=8110, path=up).mock(
        return_value=httpx.Response(201, json={"ok": True}, headers={"X-Secret": "no"})
    )
    hdrs = {
        **A,
        "X-User-Id": "usr_evil",
        "X-Internal-Token": "evil",
        "X-Supplier-Id": "sup_x",
        "Authorization": "Bearer zzz",
    }
    r = getattr(admin, method)(
        path + "?status=draft",
        headers=hdrs,
        **({"json": {"text": "hi"}} if method == "post" else {}),
    )
    assert r.status_code == 201 and r.json() == {"ok": True} and "x-secret" not in r.headers
    req = route.calls.last.request
    assert req.method == method.upper() and req.url.params["status"] == "draft"
    assert req.headers["x-user-id"] == "admin" and req.headers["x-internal-token"] == "int-secret"
    for h in ("x-admin-token", "x-supplier-id", "authorization"):
        assert h not in req.headers
    if method == "post":
        assert req.content == b'{"text":"hi"}'


def test_upstream_errors_passthrough_and_failures(admin, mock_upstream):
    mock_upstream.post(f"{D}/v1/drafts/d1/approve").mock(
        return_value=httpx.Response(429, json={"error": {"code": "cap"}})
    )
    r = admin.post("/v1/admin/demand/drafts/d1/approve", headers=A)
    assert r.status_code == 429 and r.json()["error"]["code"] == "cap"
    mock_upstream.get(f"{D}/v1/quota").mock(side_effect=httpx.ConnectError("down"))
    assert admin.get("/v1/admin/demand/quota", headers=A).status_code == 502
    mock_upstream.get(f"{D}/v1/signals").mock(side_effect=httpx.ReadTimeout("slow"))
    assert admin.get("/v1/admin/demand/signals", headers=A).status_code == 504


def test_unlisted_actions_and_paths(admin, mock_upstream):
    route = mock_upstream.route(host="localhost", port=8110).mock(
        return_value=httpx.Response(200, json={})
    )
    assert admin.post("/v1/admin/demand/drafts/d1/delete", headers=A).status_code == 404
    assert admin.delete("/v1/admin/demand/drafts/d1", headers=A).status_code in (404, 405)
    assert admin.get("/v1/admin/demand/health", headers=A).status_code in (404, 405)
    assert admin.get("/v1/admin/demand/drafts/%2E%2E", headers=A).status_code == 404
    assert not route.called


def test_overview(admin, mock_upstream):
    tok = admin.post(
        "/v1/auth/register", json={"email": "a@example.com", "password": "password123", "name": "A"}
    ).json()
    hdr = {"Authorization": f"Bearer {tok['access_token']}"}
    admin.patch("/v1/me", headers=hdr, json={"supplier_id": "sup_a"})
    route = mock_upstream.get(f"{D}/v1/drafts").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 3})
    )
    r = admin.get("/v1/admin/overview", headers=A)
    assert r.json() == {"pending_supplier_claims": 1, "pending_drafts": 3, "users": 1}
    assert route.calls.last.request.url.params["status"] == "draft"
    mock_upstream.get(f"{D}/v1/drafts").mock(side_effect=httpx.ConnectError("down"))
    assert admin.get("/v1/admin/overview", headers=A).json()["pending_drafts"] is None


def test_serve_admin_flag(make_client, tmp_path):
    (tmp_path / "index.html").write_text("<h1>x</h1>")
    off = make_client(admin_dir=str(tmp_path))
    assert off.get("/admin/").status_code == 404
    on = make_client(admin_dir=str(tmp_path), serve_admin=True)
    r = on.get("/admin/")
    assert r.status_code == 200 and "<h1>x</h1>" in r.text
