import httpx
import pytest

S = "http://localhost:8101"


def test_report_requires_auth_and_forwards_identity(make_client, mock_upstream, auth):
    c = make_client(internal_token="int-secret")
    r = c.post("/v1/auth/login", json={"email": "x@example.com", "password": "password123"})
    assert r.status_code in (401, 422)
    route = mock_upstream.route(host="localhost", port=8101, path="/v1/listings/l1/report").mock(
        return_value=httpx.Response(201, json={"ok": True})
    )
    assert c.post("/v1/listings/l1/report", json={"reason": "spam"}).status_code == 401
    assert not route.called
    reg = c.post("/v1/auth/register", json={"email": "r@example.com", "password": "password123", "name": "R"}).json()
    h = {"Authorization": f"Bearer {reg['access_token']}", "X-User-Id": "evil", "X-Supplier-Id": "evil"}
    assert c.post("/v1/listings/l1/report", json={"reason": "spam"}, headers=h).status_code == 201
    sent = route.calls.last.request.headers
    assert sent["x-user-id"] != "evil" and sent["x-internal-token"] == "int-secret"
    assert "x-supplier-id" not in sent  # not a verified supplier


def test_moderation_admin_only_and_token_injected(make_client, mock_upstream):
    c = make_client(admin_token="adm", internal_token="int", sourcing_admin_token="src-adm")
    route = mock_upstream.route(host="localhost", port=8101, path="/v1/admin/moderation/queue").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    assert c.get("/v1/admin/moderation/queue").status_code == 401
    assert c.get("/v1/admin/moderation/queue", headers={"X-Admin-Token": "bad"}).status_code == 401
    assert not route.called
    r = c.get("/v1/admin/moderation/queue?status=open", headers={"X-Admin-Token": "adm", "X-User-Id": "evil"})
    assert r.status_code == 200
    h = route.calls.last.request.headers
    assert h["x-admin-token"] == "src-adm" and h["x-internal-token"] == "int" and h["x-user-id"] == "admin"
    assert c.get("/v1/admin/moderation/../x", headers={"X-Admin-Token": "adm"}).status_code in (404, 400)


def test_moderation_disabled_without_service_token(make_client):
    c = make_client(admin_token="adm")
    assert c.get("/v1/admin/moderation/queue", headers={"X-Admin-Token": "adm"}).status_code == 404


def test_disabled_user_loses_access_within_cache_window(client, clock, mock_upstream, auth, hdr):
    mock_upstream.route(host="localhost", port=8105).mock(return_value=httpx.Response(200, json={}))
    assert client.get("/v1/requests", headers=hdr).status_code == 200
    import asyncio

    from sqlalchemy import update

    from ff_gateway.db import User

    async def disable():
        async with client.app.state.sessionmaker() as s:
            await s.execute(update(User).values(is_active=False))
            await s.commit()

    asyncio.run(disable())
    assert client.get("/v1/requests", headers=hdr).status_code == 200  # still inside the cache window
    clock.advance(6)
    r = client.get("/v1/requests", headers=hdr)
    assert r.status_code in (401, 403)


@pytest.mark.parametrize("env", ["production", "PRODUCTION"])
def test_production_guard(monkeypatch, env):
    from ff_gateway.config import Settings
    from ff_gateway.main import create_app

    monkeypatch.setenv("FF_ENV", env)
    with pytest.raises(RuntimeError, match="FF_GATEWAY_JWT_SECRET"):
        create_app(Settings(_env_file=None, database_url="sqlite+aiosqlite://"))
    with pytest.raises(RuntimeError, match="FF_GATEWAY_ADMIN_TOKEN"):
        create_app(Settings(_env_file=None, jwt_secret="x" * 40, database_url="sqlite+aiosqlite://"))
    with pytest.raises(RuntimeError, match="FF_INTERNAL_TOKEN"):
        create_app(Settings(_env_file=None, jwt_secret="x" * 40, admin_token="a", database_url="sqlite+aiosqlite://"))
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "t")
    with pytest.raises(RuntimeError, match="CORS"):
        create_app(Settings(_env_file=None, jwt_secret="x" * 40, admin_token="a", cors_origins=["*"], database_url="sqlite+aiosqlite://"))
    app = create_app(Settings(_env_file=None, jwt_secret="x" * 40, admin_token="a", database_url="sqlite+aiosqlite://"))
    from fastapi.testclient import TestClient

    c = TestClient(app)
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(p).status_code == 404
