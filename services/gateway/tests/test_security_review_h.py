"""Security review h: body limits per route class, body deadline, JWT claims/rotation, login lockout, IPv6 buckets."""

import asyncio

import httpx
import jwt
import pytest

from ff_gateway.config import Settings
from ff_gateway.domain.client_ip import rate_key
from ff_gateway.domain.clock import ManualClock
from ff_gateway.domain.errors import InvalidToken
from ff_gateway.domain.http_guard import HttpGuardMiddleware
from ff_gateway.domain.security import TokenService
from ff_gateway.obs import _CTRL

REG = {"email": "h@example.com", "password": "password123", "name": "H"}


def test_json_routes_have_a_smaller_body_cap_than_media(make_client):
    c = make_client(json_max_body_bytes=1000, max_body_bytes=5000)
    assert c.post("/v1/auth/login", content=b"x" * 1001, headers={"content-type": "application/json"}).status_code == 413
    assert c.post("/v1/media/images", content=b"x" * 3000).status_code != 413  # media class: 5000 allowed (401 here)
    assert c.post("/v1/media/images", content=b"x" * 5001).status_code == 413
    assert c.post("/v1/requests", content=b"x" * 1001).status_code == 413  # proxied JSON route, before auth/upstream work


def test_chunked_body_is_counted_without_content_length(make_client):
    c = make_client(json_max_body_bytes=1000)

    def gen():
        for _ in range(30):
            yield b"y" * 100

    r = c.post("/v1/auth/login", content=gen(), headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


def test_bad_content_length_is_400(make_client):
    c = make_client()
    r = c.post("/v1/auth/login", content=b"{}", headers={"content-length": "-5"})
    assert r.status_code in (400, 422)


def test_trickled_body_hits_the_deadline():
    sent: list[dict] = []

    async def app(scope, receive, send):
        while True:
            m = await receive()
            if m["type"] != "http.request" or not m.get("more_body"):
                break

    mw = HttpGuardMiddleware(app, 10_000, 1000, body_read_timeout=0.05, media_body_read_timeout=0.05)

    async def run():
        async def receive():
            await asyncio.sleep(1)  # never delivers in time
            return {"type": "http.request", "body": b"a", "more_body": True}

        async def send(m):
            sent.append(m)

        await mw({"type": "http", "method": "POST", "path": "/v1/auth/login", "headers": []}, receive, send)

    asyncio.run(run())
    assert sent[0]["status"] == 408


def test_auth_and_me_responses_are_not_cacheable_and_nosniff(client):
    r = client.post("/v1/auth/register", json=REG)
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_upstream_crash_pages_do_not_leak(client, mock_upstream, hdr):
    base = client.app.state.settings.upstream_map()["geo"].rstrip("/")
    mock_upstream.get(f"{base}/v1/countries").mock(
        return_value=httpx.Response(500, text="Traceback (most recent call last):\n  File '/srv/app.py'")
    )
    r = client.get("/v1/countries")
    assert r.status_code == 500
    assert "Traceback" not in r.text and r.json()["error"]["code"] == "upstream_error"
    mock_upstream.get(f"{base}/v1/cities").mock(return_value=httpx.Response(503, json={"error": {"code": "x", "message": "m"}}))
    assert client.get("/v1/cities").json()["error"]["code"] == "x"  # structured upstream errors pass untouched


def test_jwt_claims_alg_none_wrong_aud_nbf_and_rotation():
    clock = ManualClock()
    t = TokenService("s" * 40, clock, 900, 3600)
    good = t.access("u1")
    assert t.decode(good, "access") == "u1"
    now = int(clock.now().timestamp())
    base = {"sub": "u1", "typ": "access", "exp": now + 100}
    for extra in ({"aud": "other"}, {"iss": "evil"}, {"nbf": now + 500}, {"exp": "9999999999"}, {"sub": 5}):
        with pytest.raises(InvalidToken):
            t.decode(jwt.encode({**base, **extra}, "s" * 40, algorithm="HS256"), "access")
    none_tok = jwt.encode(base, None, algorithm="none")
    with pytest.raises(InvalidToken):
        t.decode(none_tok, "access")
    with pytest.raises(InvalidToken):
        t.decode(jwt.encode(base, "s" * 40, algorithm="HS512"), "access")  # algorithm confusion within HMAC family
    # legacy tokens without iss/aud still verify (rolling deploy), refresh cannot be used as access
    assert t.decode(jwt.encode(base, "s" * 40, algorithm="HS256"), "access") == "u1"
    refresh, _ = t.new_refresh("u1")
    with pytest.raises(InvalidToken):
        t.decode(refresh, "access")
    # rotation: new key signs, previous key still verifies; unknown keys never
    rotated = TokenService("n" * 40, clock, 900, 3600, previous_secret="s" * 40)
    assert rotated.decode(good, "access") == "u1"
    assert rotated.decode(rotated.access("u2"), "access") == "u2"
    with pytest.raises(InvalidToken):
        TokenService("n" * 40, clock, 900, 3600).decode(good, "access")
    with pytest.raises(ValueError):
        TokenService("s", clock, 1, 1, algorithm="none")
    with pytest.raises(ValueError):
        Settings(jwt_algorithm="none")  # type: ignore[arg-type]


def test_login_is_case_insensitive_on_email(client):
    client.post("/v1/auth/register", json=REG)
    assert client.post("/v1/auth/login", json={"email": "H@Example.com", "password": "password123"}).status_code == 200


def test_per_account_login_lockout_across_ips(make_client):
    c = make_client(login_fail_limit_per_minute=3, auth_rate_limit_per_minute=1000)
    c.post("/v1/auth/register", json=REG)
    codes = [
        c.post("/v1/auth/login", json={"email": "h@example.com", "password": f"wrong-{i}"}, headers={"x-forwarded-for": f"198.51.100.{i}"}).status_code
        for i in range(5)
    ]
    assert codes == [401, 401, 401, 429, 429]  # spoofed XFF (proxies not trusted) does not help either
    assert c.post("/v1/auth/login", json={"email": "h@example.com", "password": "password123"}).status_code == 429
    # unknown accounts are throttled identically (no enumeration through the lockout)
    codes = [c.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "x" * 9}).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_weak_passwords_are_refused(client):
    for pw in ("password", "12345678", "aaaaaaaa", "h@example.com", "abababab"[:8].replace("b", "a")):
        r = client.post("/v1/auth/register", json={**REG, "password": pw})
        assert r.status_code == 422, pw
    assert client.post("/v1/auth/register", json=REG).status_code == 201


def test_ipv6_clients_share_one_rate_bucket_per_64():
    assert rate_key("2001:db8:1:2:aaaa:bbbb:cccc:dddd") == rate_key("2001:db8:1:2::1") == "2001:db8:1:2::/64"
    assert rate_key("203.0.113.9") == "203.0.113.9" and rate_key("unknown") == "unknown"
    assert rate_key("::ffff:203.0.113.9") == "203.0.113.9"


def test_forged_xff_does_not_change_rate_bucket_when_proxies_untrusted(make_client):
    c = make_client(rate_limit_per_minute=3)
    codes = [c.get("/v1/countries", headers={"x-forwarded-for": f"198.51.100.{i}"}).status_code for i in range(6)]
    assert codes[-1] == 429


def test_log_text_format_strips_control_characters():
    assert _CTRL.sub(" ", "a\r\nforged=1 x") == "a  forged=1 x"
