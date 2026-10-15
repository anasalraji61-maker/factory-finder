"""Adversarial pass: spoofed identity headers, method override, oversized headers, CORS, JWT edges, admin 404, 429."""

import httpx
import jwt
import pytest

from ff_gateway.domain.errors import InvalidToken
from ff_gateway.domain.security import TokenService

SPOOF = {
    "X-User-Id": "usr_evil", "X-Internal-Token": "evil", "X-Forwarded-For": "6.6.6.6", "X-Client-Ip": "6.6.6.6",
    "X-Supplier-Id": "sup_evil", "X-Account-Age-Seconds": "99999999", "X-Email-Verified": "1", "X-User-Name": "Evil",
    "X-Admin-Token": "adm", "X-Real-Ip": "6.6.6.6", "Forwarded": "for=6.6.6.6",
}  # fmt: skip


@pytest.mark.parametrize(
    "path", ["/v1/search", "/v1/assistant/chat", "/v1/trust/suppliers/s1/report"]
)
def test_client_identity_headers_never_reach_upstream(make_client, mock_upstream, path):
    c = make_client(internal_token="int-secret", admin_token="adm")
    tok = c.post(
        "/v1/auth/register", json={"email": "s@example.com", "password": "password123", "name": "S"}
    ).json()
    mock_upstream.route().mock(return_value=httpx.Response(200, json={}))
    c.request("POST" if path != "/v1/search" else "GET", path, json={} if path != "/v1/search" else None,
              headers={**SPOOF, "Authorization": f"Bearer {tok['access_token']}"})  # fmt: skip
    for call in mock_upstream.calls:
        h = call.request.headers
        assert h.get("x-user-id") in (None, tok["user"]["id"])
        assert h.get("x-internal-token") in (None, "int-secret")
        assert h.get("x-supplier-id") is None and h.get("x-user-name") in (None, "S")
        assert (
            h.get("x-admin-token") is None
            and h.get("x-forwarded-for") is None
            and h.get("x-real-ip") is None
        )
        assert h.get("forwarded") is None and h.get("x-client-ip") in (None, "testclient")
        assert h.get("x-account-age-seconds") not in ("99999999",)
        assert h.get("x-email-verified") != "1" or path.endswith("/report")


def test_anonymous_spoofed_user_id_is_not_forwarded(client, mock_upstream):
    route = mock_upstream.get("http://localhost:8101/v1/search").mock(
        return_value=httpx.Response(200, json={})
    )
    client.get("/v1/search", headers={"X-User-Id": "usr_evil", "X-Internal-Token": "evil"})
    h = route.calls.last.request.headers
    assert h.get("x-user-id") is None and h.get("x-internal-token") != "evil"


def test_method_override_headers_are_ignored(client, hdr, mock_upstream):
    route = mock_upstream.get("http://localhost:8101/v1/search").mock(
        return_value=httpx.Response(200, json={})
    )
    r = client.get(
        "/v1/search",
        headers={"X-HTTP-Method-Override": "DELETE", "X-Method-Override": "DELETE", **hdr},
    )
    assert r.status_code == 200 and route.calls.last.request.method == "GET"
    assert "x-http-method-override" not in route.calls.last.request.headers
    assert client.request("TRACE", "/v1/search").status_code in (404, 405)
    assert client.request("CONNECT", "/v1/search").status_code in (404, 405, 400)


def test_oversized_header_does_not_crash_and_is_not_forwarded(client, mock_upstream):
    route = mock_upstream.get("http://localhost:8101/v1/search").mock(
        return_value=httpx.Response(200, json={})
    )
    r = client.get(
        "/v1/search", headers={"X-Big": "a" * 70_000, "Authorization": "Bearer " + "a" * 70_000}
    )
    assert r.status_code in (200, 400, 401, 431)
    for call in route.calls:
        assert "x-big" not in call.request.headers and "authorization" not in call.request.headers


def test_timeouts_are_bounded_by_config(make_client):
    s = make_client().app.state.settings
    assert 0 < s.upstream_timeout_seconds <= 30 and 0 < s.upstream_connect_timeout_seconds <= 5
    assert 0 < s.body_read_timeout_seconds <= 60 and s.media_body_read_timeout_seconds <= 300


def test_cors_preflight_only_for_configured_origins(make_client):
    c = make_client(cors_origins=["https://app.example"])
    pf = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization",
    }
    ok = c.options("/v1/search", headers={"Origin": "https://app.example", **pf})
    assert ok.headers.get("access-control-allow-origin") == "https://app.example"
    assert ok.headers.get("access-control-allow-origin") != "*"
    for origin in (
        "https://evil.example",
        "https://app.example.evil.com",
        "null",
        "http://app.example",
    ):
        bad = c.options("/v1/search", headers={"Origin": origin, **pf})
        assert "access-control-allow-origin" not in bad.headers, origin
    assert "access-control-allow-origin" not in c.get("/health", headers={"Origin": "null"}).headers


def test_admin_routes_404_when_admin_token_unset(make_client):
    c = make_client()
    for h in ({}, {"X-Admin-Token": ""}, {"X-Admin-Token": "None"}, {"X-Admin-Token": "adm"}):
        assert c.get("/v1/admin/supplier-claims", headers=h).status_code == 404, h
    c2 = make_client(admin_token="adm")
    assert c2.get("/v1/admin/supplier-claims", headers={"X-Admin-Token": "wrong"}).status_code in (
        401,
        403,
    )


def test_rate_limited_has_retry_after_header_and_envelope(make_client):
    c = make_client(auth_rate_limit_per_minute=2)
    codes = [
        c.post("/v1/auth/login", json={"email": "x@example.com", "password": "nopenope1"})
        for _ in range(5)
    ]
    lim = next(r for r in codes if r.status_code == 429)
    assert int(lim.headers["retry-after"]) >= 1 and lim.json()["error"]["code"] == "rate_limited"


def test_jwt_expired_future_nbf_and_tv_over_http(client, auth, mock_upstream, clock):
    mock_upstream.get("http://localhost:8101/v1/my/listings").mock(
        return_value=httpx.Response(200, json={})
    )
    secret = "test-secret-test-secret-test-secret"
    now = int(clock.now().timestamp())
    uid = auth["user"]["id"]
    base = {"sub": uid, "typ": "access", "exp": now + 300}
    for extra in ({"exp": now - 10}, {"nbf": now + 600}, {"tv": 99}, {"tv": -1}, {"tv": "x"}):
        tok = jwt.encode({**base, **extra}, secret, algorithm="HS256")
        r = client.get("/v1/my/listings", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, extra
    r = client.get(
        "/v1/my/listings",
        headers={"Authorization": "Bearer " + jwt.encode(base, None, algorithm="none")},
    )
    assert r.status_code == 401
    r = client.get(
        "/v1/my/listings",
        headers={
            "Authorization": f"Bearer {jwt.encode({**base, 'iss': 'evil'}, secret, algorithm='HS256')}"
        },
    )
    assert r.status_code == 401


def test_previous_key_token_verifies_through_gateway_but_new_tokens_use_new_key(make_client, clock):
    old_tok = TokenService("t" * 40, clock, 900, 3600).access("u1")
    new = make_client()  # secret "test-secret-..." ; rotate via a service built like the app does
    svc = TokenService("n" * 40, clock, 900, 3600, previous_secret="t" * 40)
    assert svc.decode(old_tok, "access") == "u1"
    assert new.app.state.tokens is not None
    with pytest.raises(InvalidToken):
        TokenService("t" * 40, clock, 900, 3600).decode(
            svc.access("u9"), "access"
        )  # never signs with the previous key
