import asyncio

import jwt as _jwt
from sqlalchemy import update

from ff_gateway.db import User
from ff_gateway.domain.clock import ManualClock
from ff_gateway.domain.security import TokenService, token_version_ok

REG = {"email": "tv@example.com", "password": "password123", "name": "TV"}


def _reg(c):
    return c.post("/v1/auth/register", json=REG).json()


def _h(tok):
    return {"Authorization": f"Bearer {tok['access_token'] if isinstance(tok, dict) else tok}"}


def _set_version(c, uid, v):
    async def go():
        async with c.app.state.sessionmaker() as s:
            await s.execute(update(User).where(User.id == uid).values(token_version=v))
            await s.commit()

    c.portal.call(go)


def test_access_token_carries_tv():
    t = TokenService("s" * 40, ManualClock(), 900, 3600)
    assert _jwt.decode(t.access("u1", 3), options={"verify_signature": False})["tv"] == 3
    assert t.decode_with_version(t.access("u1", 3), "access") == ("u1", 3)
    assert t.decode(t.access("u1"), "access") == "u1"


def test_token_version_rule():
    assert token_version_ok(2, 2) and not token_version_ok(1, 2) and not token_version_ok(3, 2)
    assert token_version_ok(None, 0) and token_version_ok(None, None) and not token_version_ok(None, 1)


def test_new_tokens_work_on_native_and_proxied_routes(client, mock_upstream):
    tok = _reg(client)
    assert client.get("/v1/me", headers=_h(tok)).status_code == 200
    base = client.app.state.settings.upstream_map()["sourcing"].rstrip("/")
    mock_upstream.get(base + "/v1/my/listings").respond(200, json={})
    assert client.get("/v1/my/listings", headers=_h(tok)).status_code == 200


def test_password_change_kills_other_access_tokens(client, mock_upstream):
    a = _reg(client)
    b = client.post("/v1/auth/login", json={"email": REG["email"], "password": REG["password"]}).json()
    base = client.app.state.settings.upstream_map()["sourcing"].rstrip("/")
    mock_upstream.get(base + "/v1/my/listings").respond(200, json={})
    r = client.post("/v1/me/password", headers=_h(a), json={"current_password": REG["password"], "new_password": "n3w-Secret-pass"})
    assert r.status_code == 200
    fresh = r.json()
    for old in (a, b):
        assert client.get("/v1/me", headers=_h(old)).status_code == 401
        assert client.get("/v1/my/listings", headers=_h(old)).status_code == 401
    assert client.get("/v1/me", headers=_h(fresh)).status_code == 200
    assert client.get("/v1/my/listings", headers=_h(fresh)).status_code == 200


def test_password_reset_kills_access_tokens(make_client):
    c = make_client(mail_backend="mock", auth_rate_limit_per_minute=1000)
    a = _reg(c)
    assert c.post("/v1/auth/password/forgot", json={"email": REG["email"]}).status_code == 202
    import re

    code = re.search(r"Reset code: (\S+)", c.app.state.mailer.outbox[-1].body).group(1)
    assert c.get("/v1/me", headers=_h(a)).status_code == 200
    assert c.post("/v1/auth/password/reset", json={"token": code, "new_password": "n3w-Secret-pass"}).status_code == 204
    assert c.get("/v1/me", headers=_h(a)).status_code == 401


def test_logout_all(client, mock_upstream):
    a = _reg(client)
    b = client.post("/v1/auth/login", json={"email": REG["email"], "password": REG["password"]}).json()
    base = client.app.state.settings.upstream_map()["sourcing"].rstrip("/")
    mock_upstream.get(base + "/v1/my/listings").respond(200, json={})
    assert client.post("/v1/auth/logout-all").status_code == 401  # needs auth
    assert client.post("/v1/auth/logout-all", headers=_h(a)).status_code == 204
    for t in (a, b):
        assert client.get("/v1/me", headers=_h(t)).status_code == 401
        assert client.get("/v1/my/listings", headers=_h(t)).status_code == 401
        assert client.post("/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    # signing in again works and yields a token for the new version
    c2 = client.post("/v1/auth/login", json={"email": REG["email"], "password": REG["password"]}).json()
    assert client.get("/v1/me", headers=_h(c2)).status_code == 200


def test_logout_all_does_not_touch_other_users(client):
    a = _reg(client)
    other = client.post("/v1/auth/register", json={"email": "o@example.com", "password": "password123", "name": "O"}).json()
    assert client.post("/v1/auth/logout-all", headers=_h(a)).status_code == 204
    assert client.get("/v1/me", headers=_h(other)).status_code == 200


def test_legacy_token_without_tv_only_while_version_zero(client, clock):
    a = _reg(client)
    uid = a["user"]["id"]
    legacy = client.app.state.tokens._encode(uid, "access", 900)  # minted before the claim existed
    assert "tv" not in _jwt.decode(legacy, options={"verify_signature": False})
    assert client.get("/v1/me", headers=_h(legacy)).status_code == 200
    _set_version(client, uid, 1)
    assert client.get("/v1/me", headers=_h(legacy)).status_code == 401
    assert client.get("/v1/me", headers=_h(a)).status_code == 401  # tv=0 != 1
    # token minted for version 1 works
    assert client.get("/v1/me", headers=_h(client.app.state.tokens.access(uid, 1))).status_code == 200


def test_deactivation_bumps_version_so_reactivation_does_not_revive_tokens(make_client):
    c = make_client(deletion_grace_days=7)
    a = _reg(c)
    assert c.request("DELETE", "/v1/me", headers=_h(a), json={"password": REG["password"]}).status_code == 202
    assert c.get("/v1/me", headers=_h(a)).status_code == 403
    c2 = c.post("/v1/auth/login", json={"email": REG["email"], "password": REG["password"]})  # cancels the deletion
    assert c2.status_code == 200
    assert c.get("/v1/me", headers=_h(a)).status_code == 401  # old token stays dead
    assert c.get("/v1/me", headers=_h(c2.json())).status_code == 200


def test_ws_ticket_and_token_handshake_respect_version(make_client, monkeypatch):
    monkeypatch.setenv("FF_GATEWAY_WS_ALLOW_TOKEN_PARAM", "true")
    c = make_client()
    a = _reg(c)
    assert c.post("/v1/ws-ticket", headers=_h(a)).status_code == 200
    assert c.post("/v1/auth/logout-all", headers=_h(a)).status_code == 204
    assert c.post("/v1/ws-ticket", headers=_h(a)).status_code == 401
    from starlette.websockets import WebSocketDisconnect

    try:
        with c.websocket_connect(f"/v1/ws/conversations/c1?token={a['access_token']}") as w:
            w.receive_text()
        raise AssertionError("expected close")
    except WebSocketDisconnect as e:
        assert e.code == 4401


def test_migration_adds_column_to_old_db():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from ff_gateway.db import create_tables

    async def go():
        eng = create_async_engine("sqlite+aiosqlite://")
        async with eng.begin() as conn:
            await conn.execute(text("CREATE TABLE users (id VARCHAR(40) PRIMARY KEY, email VARCHAR(320), phone VARCHAR(20), password_hash VARCHAR(100), name VARCHAR(200), company VARCHAR(200), role VARCHAR(10), default_destination JSON, supplier_id VARCHAR(64), display_currency VARCHAR(3), language VARCHAR(2), is_active BOOLEAN, created_at DATETIME)"))
            await conn.execute(text("INSERT INTO users (id, password_hash, name, is_active) VALUES ('u1','x','n',1)"))
        await create_tables(eng)
        async with eng.begin() as conn:
            v = (await conn.execute(text("SELECT token_version FROM users WHERE id='u1'"))).scalar()
        await eng.dispose()
        return v

    assert asyncio.run(go()) == 0
