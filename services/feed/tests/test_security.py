import pytest
from conftest import post, uh
from fastapi.testclient import TestClient

from ff_feed.config import Settings
from ff_feed.main import create_app


def mk(**kw):
    kw.setdefault("report_min_account_age_seconds", 0)
    return TestClient(create_app(Settings(database_url="sqlite+aiosqlite:///:memory:", **kw)))


def test_internal_token_guard():
    with mk(internal_token="s3cret") as c:
        assert c.get("/health").status_code == 200 and c.get("/ready").status_code == 200
        assert c.get("/v1/feed/trending").status_code == 401
        assert c.get("/v1/feed/trending", headers={"X-Internal-Token": "nope"}).status_code == 401
        assert c.get("/v1/feed/trending", headers={"X-Internal-Token": "s3cret"}).status_code == 200
        assert c.get("/v1/admin/feed/posts").status_code == 401  # guard comes first


def test_internal_token_from_shared_env(monkeypatch):
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "envtoken")
    with mk() as c:
        assert c.get("/v1/feed/trending").status_code == 401
        assert c.get("/v1/feed/trending", headers={"X-Internal-Token": "envtoken"}).status_code == 200


def test_production_requires_internal_token(monkeypatch):
    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="FF_INTERNAL_TOKEN"):
        mk()
    mk(internal_token="x")  # ok with a token
    monkeypatch.setenv("FF_ENV", "development")
    mk()


@pytest.mark.parametrize("user", ["has space", "a" * 129, "semi;colon", "<script>"])
def test_bad_user_id_is_401(client, user):
    assert client.get("/v1/feed/home", headers={"X-User-Id": user}).status_code == 401


def test_error_shape(client):
    r = client.get("/v1/feed/posts/post_missing", headers=uh())
    assert r.json() == {"error": {"code": "not_found", "message": "Post not found", "details": {}}}
    r = client.post("/v1/feed/posts", headers=uh(), json={"body": "x"})
    assert set(r.json()["error"]) == {"code", "message", "details"}
    assert client.get("/v1/nope").status_code == 404


def test_supplier_identity_comes_only_from_header(client):
    r = client.post(
        "/v1/feed/posts", headers=uh("u1", "sup_real"), json={"body": "hi", "supplier_id": "sup_fake"}
    )
    assert r.status_code == 422  # body cannot carry identity
    assert post(client, supplier="sup_real")["supplier_id"] == "sup_real"


def test_injection_like_ids_rejected(client):
    assert client.get("/v1/feed/posts/x'%20OR%201=1", headers=uh()).status_code in (404, 422)
    assert client.put("/v1/feed/posts/..%2f..%2fetc/like", headers=uh()).status_code in (404, 422)
