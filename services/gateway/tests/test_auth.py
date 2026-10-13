from datetime import UTC, datetime

import jwt

REG = {"email": "A@Example.com", "password": "password123", "name": "Anas"}


def test_register_login_me(client):
    r = client.post("/v1/auth/register", json=REG)
    assert r.status_code == 201
    body = r.json()
    assert body["expires_in"] == 900 and body["user"]["email"] == "a@example.com" and body["user"]["role"] == "buyer"
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
    assert client.post("/v1/auth/login", json={"phone": "+9647701234567", "password": "password123"}).status_code == 200


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
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200
    clock.advance(31 * 24 * 3600)
    r = client.post("/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]})
    assert r.status_code == 401 and r.json()["error"]["code"] == "token_expired"


def test_token_type_confusion_rejected(client, auth):
    r = client.get("/v1/me", headers={"Authorization": f"Bearer {auth['refresh_token']}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
    r = client.post("/v1/auth/refresh", json={"refresh_token": auth["access_token"]})
    assert r.status_code == 401


def test_garbage_and_forged_tokens(client, auth):
    assert client.get("/v1/me", headers={"Authorization": "Bearer abc"}).json()["error"]["code"] == "invalid_token"
    forged = jwt.encode({"sub": "x", "typ": "access", "exp": int(datetime(2099, 1, 1, tzinfo=UTC).timestamp())}, "other", algorithm="HS256")
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    r = client.get("/v1/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "authentication_required"


def test_generated_secret_when_unset(caplog):
    from ff_gateway.config import Settings

    s = Settings(jwt_secret=None)
    with caplog.at_level("WARNING", logger="ff_gateway"):
        secret = s.resolved_secret()
    assert len(secret) >= 32 and "ephemeral" in caplog.text and s.resolved_secret() == secret
