"""Adversarial auth/hardening: JWT edge cases, password policy, login throttle, deletion cascade, CORS, request-id, envelopes."""

import base64
import json

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from ff_gateway.config import Settings
from ff_gateway.db import EmailVerificationToken, PasswordResetToken, RefreshToken
from ff_gateway.main import create_app

SECRET = "test-secret-test-secret-test-secret"
PW = "password123"


def _reg(c, email="a@example.com", phone=None, pw=PW):
    body = {"password": pw, "name": "N", **({"email": email} if email else {}), **({"phone": phone} if phone else {})}
    return c.post("/v1/auth/register", json=body)


def _code(r):
    return r.json()["error"]["code"]


def _claims(clock, **kw):
    now = int(clock.now().timestamp())
    return {"sub": "u1", "typ": "access", "iss": "ff-gateway", "aud": "ff-api", "iat": now, "exp": now + 600, **kw}


# ---------------------------------------------------------------- JWT over HTTP
def test_jwt_edge_cases_all_401_with_envelope(client, auth, clock):
    uid = auth["user"]["id"]
    good = _claims(clock, sub=uid, tv=0)
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    tokens = {
        "alg_none": jwt.encode(good, None, algorithm="none"),
        "alg_none_fake_sig": b64({"alg": "none", "typ": "JWT"}) + "." + b64(good) + ".c2ln",
        "wrong_key_wrong_kid": jwt.encode(good, "x" * 40, algorithm="HS256", headers={"kid": "nope"}),
        "expired": jwt.encode(_claims(clock, sub=uid, tv=0, exp=int(clock.now().timestamp()) - 1), SECRET, algorithm="HS256"),
        "tv_mismatch": jwt.encode({**good, "tv": 7}, SECRET, algorithm="HS256"),
        "tv_string": jwt.encode({**good, "tv": "0"}, SECRET, algorithm="HS256"),
        "tv_bool": jwt.encode({**good, "tv": True}, SECRET, algorithm="HS256"),
        "refresh_as_access": jwt.encode({**good, "typ": "refresh"}, SECRET, algorithm="HS256"),
        "jku_header": jwt.encode(good, "x" * 40, algorithm="HS256", headers={"jku": "http://evil/jwks"}),
        "garbage": "not.a.jwt",
        "dots": "....",
        "unicode": "tökén.ünï.çødé‮",
        "emoji": "\U0001f600" * 50,
        "huge": "A" * 6000 + "." + "B" * 6000 + "." + "C" * 6000,
    }
    for name, tok in tokens.items():
        try:
            r = client.get("/v1/me", headers={"Authorization": f"Bearer {tok}"})
        except Exception as e:  # httpx refuses non-ascii header values client-side: send them as raw bytes below
            assert name in ("unicode", "emoji"), (name, e)
            continue
        assert r.status_code == 401, (name, r.status_code)
        assert _code(r) in ("invalid_token", "token_expired"), name
        assert set(r.json()["error"]) == {"code", "message", "details"}


def test_non_ascii_and_oversized_authorization_headers_never_500(client):
    for raw in ("Bearer tökén".encode("latin-1"), b"Bearer " + b"\xff\xfe\xfd", b"Bearer " + b"A" * 70_000, b"Bearer", b"Bearer  "):
        r = client.get("/v1/me", headers=[(b"authorization", raw)])
        assert r.status_code in (400, 401, 431), raw[:20]
        if r.headers.get("content-type", "").startswith("application/json"):
            assert "error" in r.json()


def test_unicode_and_null_in_token_claims(clock):
    from ff_gateway.domain.errors import InvalidToken
    from ff_gateway.domain.security import TokenService

    t = TokenService(SECRET, clock, 900, 3600)
    for extra in ({"sub": "\u0000"}, {"sub": ["a"]}, {"sub": {"a": 1}}, {"exp": float("nan")}, {"exp": None}, {"tv": 1.5}, {"tv": []}):
        c = {**_claims(clock), **extra}
        try:
            tok = jwt.encode(c, SECRET, algorithm="HS256")
        except Exception:
            continue
        try:
            t.decode(tok, "access")
        except InvalidToken:
            pass
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"{extra}: non-401 failure {type(e).__name__}")


# ---------------------------------------------------------------- passwords
def test_password_policy_edges(client):
    cases = {
        "short": "abc12",
        "too_long": "a1" * 65,  # 130 chars
        "blank": " " * 12,
        "repeat": "ab" * 6,
        "common": "Password",
        "same_as_email": "Zed@example.com",
        "over_72_bytes": "éa" * 20,  # 80 bytes: bcrypt would silently ignore the tail
    }
    for name, pw in cases.items():
        r = _reg(client, "zed@example.com", pw=pw)
        assert r.status_code == 422, (name, r.status_code)
        assert _code(r) == "validation_error"
        assert pw not in r.text or name == "blank"  # the password is never echoed back
    assert _reg(client, "zed@example.com", pw="pässwörd-ünïcode-123").status_code == 201


def test_password_tail_beyond_72_bytes_is_not_silently_ignored(client):
    long_pw = "x9" * 36 + "tail"  # 76 bytes ascii
    assert _reg(client, "lp@example.com", pw=long_pw).status_code in (201, 422)
    r = client.post("/v1/auth/login", json={"email": "lp@example.com", "password": "x9" * 36 + "other"})
    assert r.status_code == 401  # either rejected at register (422 above, no account) or the tail matters


def test_password_in_validation_error_is_not_echoed(client):
    r = client.post("/v1/auth/register", json={"email": "not-an-email", "password": "SuperSecret-123", "name": "x"})
    assert r.status_code == 422 and "SuperSecret-123" not in r.text


# ---------------------------------------------------------------- login throttling
def test_lockout_cannot_be_dodged_by_rotating_the_other_identifier(make_client):
    c = make_client(login_fail_limit_per_minute=3, auth_rate_limit_per_minute=1000)
    _reg(c, "v@example.com", phone="+15550001111")
    codes = [
        c.post("/v1/auth/login", json={"phone": "+15550001111", "email": f"rot{i}@example.com", "password": f"guess-{i}-xx"}).status_code
        for i in range(6)
    ]
    assert codes[-1] == 429, codes  # the phone bucket fills no matter which email rides along
    # and a mismatched pair never authenticates as either account
    assert c.post("/v1/auth/login", json={"phone": "+15550001111", "email": "other@example.com", "password": PW}).status_code in (401, 429)


def test_lockout_ignores_spoofed_ip_headers_and_case(make_client):
    c = make_client(login_fail_limit_per_minute=3, auth_rate_limit_per_minute=1000)
    _reg(c, "case@example.com")
    variants = ["case@example.com", "CASE@example.com", "Case@Example.com", "case@EXAMPLE.com"]
    codes = [
        c.post("/v1/auth/login", json={"email": v, "password": f"wrong-{i}x"}, headers={"x-forwarded-for": f"203.0.113.{i}", "x-real-ip": f"10.0.0.{i}"}).status_code
        for i, v in enumerate(variants + variants)
    ]
    assert codes[:3] == [401, 401, 401] and set(codes[3:]) == {429}


# ---------------------------------------------------------------- registration responses
def test_duplicate_registration_error_is_generic_envelope_without_leaking_account_data(client):
    assert _reg(client, "dup@example.com").status_code == 201
    r = _reg(client, "DUP@example.com")
    assert r.status_code == 409 and _code(r) == "account_exists"
    blob = r.text.lower()
    for leak in ("id", "hash", "created", "dup@example.com"):
        assert leak not in json.dumps(r.json()["error"]["details"]).lower() or leak == "id", leak
    assert "$2b$" not in blob


# ---------------------------------------------------------------- deletion cascade
def test_deletion_removes_all_tokens_and_tickets(make_client, mock_upstream):
    mock_upstream.route(url__regex=r"http://localhost:81\d\d/v1/internal/users/.*").mock(
        return_value=httpx.Response(200, json={"status": "done"})
    )
    c = make_client(mail_backend="mock")
    t = _reg(c, "gone@example.com").json()
    h = {"Authorization": f"Bearer {t['access_token']}"}
    uid = t["user"]["id"]
    c.post("/v1/auth/password/forgot", json={"email": "gone@example.com"})
    c.post("/v1/auth/resend-verification", json={"email": "gone@example.com"})
    ticket = c.post("/v1/ws-ticket", headers=h).json()["ticket"]

    async def counts():
        async with c.app.state.sessionmaker() as s:
            return [
                await s.scalar(select(func.count()).select_from(m).where(m.user_id == uid))
                for m in (RefreshToken, PasswordResetToken, EmailVerificationToken)
            ]

    before = c.portal.call(counts)
    assert before[0] >= 1 and before[1] >= 1
    assert c.request("DELETE", "/v1/me", headers=h, json={"password": PW}).status_code == 200
    assert c.portal.call(counts) == [0, 0, 0]
    # the pre-issued ws ticket is useless, the old tokens and the refresh token are dead
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as ei, c.websocket_connect(f"/v1/ws/conversations/c1?ticket={ticket}") as w:
        w.receive_text()
    assert ei.value.code == 4401
    assert c.get("/v1/me", headers=h).status_code in (401, 403)
    assert c.post("/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert c.post("/v1/auth/login", json={"email": "gone@example.com", "password": PW}).status_code == 401
    assert c.post("/v1/ws-ticket", headers=h).status_code in (401, 403)


def test_ws_ticket_cannot_be_revived_by_cancelling_a_grace_period_deletion(make_client, mock_upstream):
    mock_upstream.route(url__regex=r"http://localhost:81\d\d/v1/internal/users/.*").mock(
        return_value=httpx.Response(200, json={"status": "done"})
    )
    c = make_client(deletion_grace_days=7)
    t = _reg(c, "grace@example.com").json()
    h = {"Authorization": f"Bearer {t['access_token']}"}
    ticket = c.post("/v1/ws-ticket", headers=h).json()["ticket"]
    assert c.request("DELETE", "/v1/me", headers=h, json={"password": PW}).status_code == 202
    assert c.post("/v1/auth/login", json={"email": "grace@example.com", "password": PW}).status_code == 200  # cancels
    assert c.app.state.ws_tickets.consume_sync(ticket) is None  # but the old ticket stays dead


# ---------------------------------------------------------------- CORS
@pytest.mark.parametrize("bad", [["*"], ["https://ok.example", "*"], [" * "], ["null"]])
def test_production_refuses_unsafe_cors_origins(monkeypatch, bad):
    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "i" * 40)
    s = Settings(jwt_secret="j" * 40, admin_token="a" * 40, database_url="sqlite+aiosqlite://", cors_origins=bad)
    with pytest.raises(RuntimeError, match="CORS"):
        create_app(s)


def test_cors_never_allows_credentials_or_wildcard_when_configured(make_client):
    c = make_client(cors_origins=["https://app.example"])
    r = c.options("/v1/me", headers={"Origin": "https://app.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "https://app.example"
    assert "access-control-allow-credentials" not in r.headers
    g = c.get("/health", headers={"Origin": "https://app.example"})
    assert "x-request-id" in g.headers.get("access-control-expose-headers", "").lower()
    assert "access-control-allow-credentials" not in g.headers
    c2 = make_client()
    r = c2.options("/v1/me", headers={"Origin": "https://app.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


# ---------------------------------------------------------------- request id + envelopes
def test_request_id_propagation_and_sanitising(client):
    r = client.get("/health", headers={"X-Request-Id": "abc-123_X.y"})
    assert r.headers["x-request-id"] == "abc-123_X.y"
    for bad in ("a" * 65, "id with space", "x;y", "ü" * 3, ""):
        try:
            r = client.get("/health", headers={"X-Request-Id": bad})
        except Exception:
            continue
        rid = r.headers["x-request-id"]
        assert rid != bad and len(rid) == 32, bad
    r1, r2 = client.get("/health"), client.get("/health")
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


def test_request_id_is_forwarded_upstream(client, mock_upstream):
    base = client.app.state.settings.upstream_map()["geo"].rstrip("/")
    route = mock_upstream.get(f"{base}/v1/countries").mock(return_value=httpx.Response(200, json=[]))
    client.get("/v1/countries", headers={"X-Request-Id": "trace-42"})
    assert route.calls.last.request.headers["x-request-id"] == "trace-42"


def _boom_app(client):
    from fastapi import APIRouter

    r = APIRouter()

    @r.get("/v1/_boom")
    async def boom():
        raise RuntimeError("secret-internal-detail /srv/app.py")

    @r.get("/v1/_boom_val")
    async def boom_val():
        int("x")  # ValueError

    client.app.router.routes[:0] = r.routes
    return TestClient(client.app, raise_server_exceptions=False)


def test_unhandled_exception_is_enveloped_without_stack_and_keeps_request_id(client):
    c = _boom_app(client)
    for path in ("/v1/_boom", "/v1/_boom_val"):
        r = c.get(path, headers={"X-Request-Id": "rid-500"})
        assert r.status_code == 500
        assert r.json() == {"error": {"code": "internal_error", "message": "Internal server error", "details": {}}}
        assert "Traceback" not in r.text and "secret-internal" not in r.text and "/srv/" not in r.text
        assert r.headers["x-request-id"] == "rid-500"


def test_unhandled_exception_carries_cors_headers_for_configured_origin(make_client):
    c = _boom_app(make_client(cors_origins=["https://app.example"]))
    r = c.get("/v1/_boom", headers={"Origin": "https://app.example"})
    assert r.status_code == 500 and r.headers.get("access-control-allow-origin") == "https://app.example"


def test_every_4xx_5xx_uses_the_same_envelope(client, hdr):
    cases = [
        ("GET", "/v1/me", {}, None, 401),
        ("GET", "/v1/nope-not-here", {}, None, (401, 404)),
        ("DELETE", "/health", {}, None, (404, 405)),
        ("POST", "/v1/auth/login", {}, b"{not json", 422),
        ("POST", "/v1/auth/login", {"content-type": "application/json"}, b"\xff\xfe\x00", (400, 422)),
        ("POST", "/v1/auth/login", {"content-type": "application/json"}, b'{"email":"a@b.co","password":"x","evil":1}', 422),
        ("POST", "/v1/auth/login", {"content-type": "text/plain"}, b"x", 422),
        ("POST", "/v1/auth/register", {"content-type": "application/json"}, b"[]", 422),
        ("POST", "/v1/auth/login", {"content-type": "application/json"}, b"x" * (2 << 20), 413),
        ("POST", "/v1/auth/refresh", {"content-type": "application/json"}, b'{"refresh_token":"zzz"}', 401),
        ("GET", "/v1/admin/users", {}, None, (401, 403, 404)),
        ("GET", "/v1/me/../admin/x", {}, None, (400, 401, 404)),
        ("GET", "/v1/%00", {}, None, (400, 401, 404)),
    ]
    for method, path, headers, body, want in cases:
        r = client.request(method, path, headers=headers, content=body)
        want = want if isinstance(want, tuple) else (want,)
        assert r.status_code in want, (method, path, r.status_code, r.text[:200])
        assert r.headers["content-type"].startswith("application/json"), (path, r.headers["content-type"])
        e = r.json()["error"]
        assert set(e) == {"code", "message", "details"} and isinstance(e["code"], str) and isinstance(e["details"], dict), path
        assert "Traceback" not in r.text and "File \"" not in r.text
        assert r.headers.get("x-request-id")
