from datetime import UTC, datetime

import jwt

REG = {"email": "A@Example.com", "password": "password123", "name": "Anas"}


def test_register_login_me(client):
    r = client.post("/v1/auth/register", json=REG)
    assert r.status_code == 201
    body = r.json()
    assert (
        body["expires_in"] == 900
        and body["user"]["email"] == "a@example.com"
        and body["user"]["role"] == "buyer"
    )
    assert "password" not in str(body)
    r = client.post("/v1/auth/login", json={"email": "a@example.com", "password": "password123"})
    assert r.status_code == 200
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.json()["name"] == "Anas"


def test_register_with_phone_and_duplicates(client):
    body = {"phone": "+964 770 123-4567", "password": "password123", "name": "P"}
    r = client.post("/v1/auth/register", json=body)
    assert r.status_code == 201 and r.json()["user"]["phone"] == "+9647701234567"
    dup = client.post("/v1/auth/register", json=body)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "account_exists"
    assert (
        client.post(
            "/v1/auth/login", json={"phone": "+9647701234567", "password": "password123"}
        ).status_code
        == 200
    )


def test_register_validation(client):
    for bad in [
        {"password": "password123", "name": "x"},
        {"email": "a@example.com", "password": "short", "name": "x"},
        {"email": "nope", "password": "password123", "name": "x"},
        {"phone": "12", "password": "password123", "name": "x"},
    ]:
        r = client.post("/v1/auth/register", json=bad)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_login_wrong_password_and_unknown_user_same_error(client, auth):
    a = client.post("/v1/auth/login", json={"email": "a@example.com", "password": "wrongwrong"})
    b = client.post("/v1/auth/login", json={"email": "zzz@example.com", "password": "wrongwrong"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() and a.json()["error"]["code"] == "invalid_credentials"


def test_access_token_expires_and_refresh_works(client, clock, auth):
    h = {"Authorization": f"Bearer {auth['access_token']}"}
    assert client.get("/v1/me", headers=h).status_code == 200
    clock.advance(901)
    r = client.get("/v1/me", headers=h)
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"
    r = client.post("/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]})
    assert r.status_code == 200
    assert (
        client.get(
            "/v1/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
        ).status_code
        == 200
    )
    clock.advance(31 * 24 * 3600)
    r = client.post("/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]})
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"


def test_token_type_confusion_rejected(client, auth):
    r = client.get("/v1/me", headers={"Authorization": f"Bearer {auth['refresh_token']}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
    r = client.post("/v1/auth/refresh", json={"refresh_token": auth["access_token"]})
    assert r.status_code == 401


def test_garbage_and_forged_tokens(client, auth):
    assert (
        client.get("/v1/me", headers={"Authorization": "Bearer abc"}).json()["error"]["code"]
        == "invalid_token"
    )
    forged = jwt.encode(
        {"sub": "x", "typ": "access", "exp": int(datetime(2099, 1, 1, tzinfo=UTC).timestamp())},
        "other",
        algorithm="HS256",
    )
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    r = client.get("/v1/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "authentication_required"


def test_generated_secret_when_unset(caplog):
    from ff_gateway.config import Settings

    s = Settings(jwt_secret=None)
    with caplog.at_level("WARNING", logger="ff_gateway"):
        secret = s.resolved_secret()
    assert len(secret) >= 32 and "ephemeral" in caplog.text and s.resolved_secret() == secret


def _refresh(client, tok):
    return client.post("/v1/auth/refresh", json={"refresh_token": tok})


def test_refresh_rotates_and_shape_unchanged(client, auth):
    r = _refresh(client, auth["refresh_token"])
    assert r.status_code == 200
    b = r.json()
    assert set(b) >= {"access_token", "refresh_token", "token_type", "expires_in"}
    assert b["refresh_token"] != auth["refresh_token"]
    assert _refresh(client, b["refresh_token"]).status_code == 200  # chain keeps working


def test_refresh_reuse_revokes_family(client, auth):
    r1 = _refresh(client, auth["refresh_token"]).json()
    r2 = _refresh(client, r1["refresh_token"]).json()
    replay = _refresh(client, auth["refresh_token"])  # stolen/old token replayed
    assert replay.status_code == 401 and replay.json()["error"]["code"] == "invalid_token"
    assert (
        _refresh(client, r2["refresh_token"]).status_code == 401
    )  # newest token of the family is dead too


def test_refresh_reuse_does_not_touch_other_sessions(client, auth):
    other = client.post(
        "/v1/auth/login", json={"email": "a@example.com", "password": "password123"}
    ).json()
    r1 = _refresh(client, auth["refresh_token"]).json()
    assert _refresh(client, auth["refresh_token"]).status_code == 401
    assert _refresh(client, r1["refresh_token"]).status_code == 401
    assert _refresh(client, other["refresh_token"]).status_code == 200


def test_logout_revokes_family_and_is_idempotent(client, auth):
    r1 = _refresh(client, auth["refresh_token"]).json()
    assert (
        client.post("/v1/auth/logout", json={"refresh_token": r1["refresh_token"]}).status_code
        == 204
    )
    assert _refresh(client, r1["refresh_token"]).status_code == 401
    assert (
        client.post("/v1/auth/logout", json={"refresh_token": r1["refresh_token"]}).status_code
        == 204
    )
    assert client.post("/v1/auth/logout", json={"refresh_token": "garbage"}).status_code == 204


def test_untracked_refresh_token_rejected(client, auth):
    import jwt as _jwt

    forged = _jwt.encode(
        {"sub": "usr_x", "typ": "refresh", "exp": 9999999999, "jti": "nope", "fam": "f"},
        "test-secret-test-secret-test-secret",
        algorithm="HS256",
    )
    assert _refresh(client, forged).status_code == 401
    legacy = _jwt.encode(
        {"sub": "usr_x", "typ": "refresh", "exp": 9999999999},
        "test-secret-test-secret-test-secret",
        algorithm="HS256",
    )
    assert _refresh(client, legacy).status_code == 401


def test_refresh_stores_only_hashed_jti(client, auth):
    import jwt as _jwt

    jti = _jwt.decode(auth["refresh_token"], options={"verify_signature": False})["jti"]
    from sqlalchemy import select

    from ff_gateway.db import RefreshToken

    async def rows():
        async with client.app.state.sessionmaker() as s:
            return [r.jti_hash for r in (await s.scalars(select(RefreshToken))).all()]

    import asyncio

    hashes = asyncio.run(rows())
    assert hashes and jti not in hashes


def test_register_per_ip_hourly_throttle(make_client, clock):
    c = make_client(register_per_hour=3)
    for i in range(3):
        assert c.post("/v1/auth/register", json={**REG, "email": f"u{i}@example.com"}).status_code == 201
    r = c.post("/v1/auth/register", json={**REG, "email": "u0@example.com"})  # existing identifiers count too
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and "Retry-After" in r.headers


def test_register_throttle_off_and_409_kept(make_client):
    c = make_client(register_per_hour=0)
    for i in range(12):
        c.post("/v1/auth/register", json={**REG, "email": f"v{i}@example.com"})
    assert c.post("/v1/auth/register", json={**REG, "email": "v0@example.com"}).status_code == 409
