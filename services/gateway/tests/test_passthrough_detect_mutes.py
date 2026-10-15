import httpx
import pytest


def _url(c, name):
    return c.app.state.settings.upstream_map()[name].rstrip("/")


def _token(c, email):
    reg = c.post("/v1/auth/register", json={"email": email, "password": "password123", "name": "T"}).json()
    return {"Authorization": f"Bearer {reg['access_token']}"}


def test_references_detect_requires_auth_and_forwards_clean(make_client, mock_upstream):
    c = make_client(internal_token="int-secret")
    route = mock_upstream.get(_url(c, "tracking") + "/v1/references/detect").mock(
        return_value=httpx.Response(200, json={"type": "container"})
    )
    assert c.get("/v1/references/detect?q=MSKU1234567").status_code == 401
    assert not route.called
    h = {**_token(c, "det@example.com"), "X-User-Id": "evil", "X-Supplier-Id": "sup_evil", "X-Internal-Token": "x"}
    assert c.get("/v1/references/detect?q=MSKU1234567", headers=h).status_code == 200
    sent = route.calls.last.request
    assert sent.url.params["q"] == "MSKU1234567"
    assert sent.headers["x-user-id"] != "evil" and "x-supplier-id" not in sent.headers
    assert sent.headers["x-internal-token"] == "int-secret"


def test_hs_suggest_public_get_only(make_client, mock_upstream):
    c = make_client()
    route = mock_upstream.get(_url(c, "logistics") + "/v1/hs/suggest").mock(return_value=httpx.Response(200, json={"items": []}))
    r = c.get("/v1/hs/suggest?q=pump&limit=3", headers={"X-User-Id": "evil"})
    assert r.status_code == 200
    sent = route.calls.last.request
    assert sent.url.params["q"] == "pump" and "x-user-id" not in sent.headers
    assert c.post("/v1/hs/suggest", json={}).status_code == 401


@pytest.mark.parametrize(("method", "path"), [("GET", "/v1/feed/mutes"), ("PUT", "/v1/feed/mutes/sup_1"), ("DELETE", "/v1/feed/mutes/sup_1")])
def test_feed_mutes_auth_and_identity(make_client, mock_upstream, method, path):
    c = make_client(internal_token="int-secret")
    route = mock_upstream.route(method=method, url=_url(c, "feed") + path).mock(return_value=httpx.Response(200, json={}))
    assert c.request(method, path).status_code == 401
    assert not route.called
    h = {**_token(c, f"m{method.lower()}@example.com"), "X-User-Id": "evil", "X-Supplier-Id": "sup_evil"}
    assert c.request(method, path, headers=h).status_code == 200
    sent = route.calls.last.request
    assert sent.method == method
    assert sent.headers["x-user-id"] != "evil" and "x-supplier-id" not in sent.headers  # unverified claim: never client-supplied
    assert sent.headers["x-internal-token"] == "int-secret"


def test_requests_cursor_forwarded(make_client, mock_upstream):
    c = make_client()
    route = mock_upstream.get(_url(c, "rfq") + "/v1/requests").mock(return_value=httpx.Response(200, json={"items": []}))
    r = c.get("/v1/requests?cursor=abc%3D%3D&limit=5&status=open", headers=_token(c, "cur@example.com"))
    assert r.status_code == 200
    p = route.calls.last.request.url.params
    assert p["cursor"] == "abc==" and p["limit"] == "5" and p["status"] == "open"
