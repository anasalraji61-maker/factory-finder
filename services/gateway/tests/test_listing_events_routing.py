import httpx
import pytest

from ff_gateway.domain.routing import is_public

S = "http://localhost:8101"


@pytest.mark.parametrize(
    ("method", "path", "public"),
    [
        ("POST", "/v1/listings/nat_abc12345/events", True),
        ("POST", "/v1/listings/nat_abc12345/events/", True),
        ("POST", "/v1/listings/a/b/events", False),
        ("POST", "/v1/listings/nat_abc12345/report", False),
        ("GET", "/v1/my/analytics", False),
    ],
)
def test_events_public_policy(method, path, public):
    assert is_public(method, path) is public


def test_events_anonymous_forwards_peer_ip_and_never_client_headers(make_client, mock_upstream):
    c = make_client(internal_token="int-secret")
    route = mock_upstream.route(host="localhost", port=8101, path="/v1/listings/nat_abc12345/events").mock(
        return_value=httpx.Response(202, json={"counted": True})
    )
    r = c.post(
        "/v1/listings/nat_abc12345/events", json={"type": "view"},
        headers={"X-Client-Ip": "6.6.6.6", "X-User-Id": "evil", "X-Forwarded-For": "7.7.7.7"},
    )
    assert r.status_code == 202
    sent = route.calls.last.request.headers
    assert sent["x-client-ip"] not in ("6.6.6.6", "7.7.7.7")  # direct peer (no trusted proxy configured)
    assert "x-user-id" not in sent and sent["x-internal-token"] == "int-secret"


def test_events_with_token_forward_user_identity(make_client, mock_upstream):
    c = make_client()
    route = mock_upstream.route(host="localhost", port=8101, path="/v1/listings/nat_abc12345/events").mock(
        return_value=httpx.Response(202, json={"counted": True})
    )
    reg = c.post("/v1/auth/register", json={"email": "ev@example.com", "password": "password123", "name": "E"}).json()
    h = {"Authorization": f"Bearer {reg['access_token']}", "X-User-Id": "evil"}
    assert c.post("/v1/listings/nat_abc12345/events", json={"type": "share"}, headers=h).status_code == 202
    assert route.calls.last.request.headers["x-user-id"] != "evil"


def test_my_analytics_requires_auth_and_forwards_only_verified_supplier(make_client, mock_upstream):
    c = make_client()
    route = mock_upstream.route(host="localhost", port=8101, path="/v1/my/analytics").mock(
        return_value=httpx.Response(200, json={"totals": {}})
    )
    assert c.get("/v1/my/analytics?days=7").status_code == 401
    assert not route.called
    reg = c.post("/v1/auth/register", json={"email": "an@example.com", "password": "password123", "name": "A"}).json()
    h = {"Authorization": f"Bearer {reg['access_token']}", "X-Supplier-Id": "sup_evil"}
    assert c.get("/v1/my/analytics?days=7&listing_id=nat_1", headers=h).status_code == 200
    sent = route.calls.last.request
    assert "x-supplier-id" not in sent.headers and sent.url.params["days"] == "7"
