import pytest
from conftest import make_forwarder, make_quote, make_request, uh
from fastapi.testclient import TestClient

from ff_freight.config import Settings
from ff_freight.main import create_app


def mk(**kw):
    return TestClient(create_app(Settings(database_url="sqlite+aiosqlite:///:memory:", **kw)))


def test_internal_token_guard():
    with mk(internal_token="s3cret") as c:
        assert c.get("/health").status_code == 200 and c.get("/ready").status_code == 200
        assert c.get("/v1/freight/forwarders", headers=uh()).status_code == 401
        assert c.get("/v1/freight/forwarders", headers={**uh(), "X-Internal-Token": "nope"}).status_code == 401
        assert c.get("/v1/freight/forwarders", headers={**uh(), "X-Internal-Token": "s3cret"}).status_code == 200
        assert c.get("/v1/admin/freight/applications").status_code == 401  # guard comes first


def test_internal_token_from_shared_env(monkeypatch):
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "envtoken")
    with mk() as c:
        assert c.get("/v1/freight/forwarders", headers=uh()).status_code == 401
        assert c.get("/v1/freight/forwarders", headers={**uh(), "X-Internal-Token": "envtoken"}).status_code == 200


def test_production_requires_internal_token(monkeypatch):
    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="FF_INTERNAL_TOKEN"):
        mk()
    mk(internal_token="x")  # ok with a token
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "from-env")
    mk()
    monkeypatch.setenv("FF_ENV", "development")
    monkeypatch.delenv("FF_INTERNAL_TOKEN")
    mk()


@pytest.mark.parametrize("user", ["has space", "a" * 129, "semi;colon", "<script>"])
def test_bad_user_id_is_401(client, user):
    assert client.get("/v1/freight/requests", headers={"X-User-Id": user}).status_code == 401


def test_error_shape(client):
    r = client.get("/v1/freight/requests/shp_missing", headers=uh())
    assert r.json() == {"error": {"code": "not_found", "message": "Request not found", "details": {}}}
    r = client.post("/v1/freight/requests", headers=uh(), json={"origin_country": "CN"})
    assert r.status_code == 422 and set(r.json()["error"]) == {"code", "message", "details"}
    assert client.get("/v1/nope").status_code == 404


def test_forwarder_identity_comes_only_from_approved_table(client):
    """No header or body can make a user a forwarder; only an admin approval does."""
    req = make_request(client)
    spoof = {**uh("mallory"), "X-Forwarder-Id": "fwd_anything", "X-Supplier-Id": "sup_x"}
    from conftest import QUOTE

    r = client.post(f"/v1/freight/requests/{req['id']}/quotes", headers=spoof, json=QUOTE)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forwarder_required"
    assert client.get("/v1/freight/forwarders/me", headers=spoof).status_code == 403
    assert client.get("/v1/freight/me", headers=spoof).json()["forwarder_id"] is None
    assert client.post(f"/v1/freight/requests/{req['id']}/quotes", headers=uh("mallory"), json={**QUOTE, "forwarder_id": "fwd_x"}).status_code == 422
    # a pending application is not an identity either
    from conftest import APP

    client.post("/v1/freight/applications", headers=uh("mallory"), json=APP)
    assert client.post(f"/v1/freight/requests/{req['id']}/quotes", headers=spoof, json=QUOTE).status_code == 403
    # approving mallory's application does not let someone else use mallory's forwarder id
    fid = make_forwarder(client, "alice")
    r = client.post(f"/v1/freight/requests/{req['id']}/quotes", headers={**uh("bob"), "X-Forwarder-Id": fid}, json=QUOTE)
    assert r.status_code == 403


def test_users_cannot_touch_each_others_data(client):
    make_forwarder(client, "fa")
    make_forwarder(client, "fb")
    req = make_request(client)
    q = make_quote(client, req["id"], "fa")
    assert client.put(f"/v1/freight/quotes/{q['id']}", headers=uh("fb"), json={"amount": "1", "currency": "USD", "transit_days": 1}).status_code == 404
    assert client.post(f"/v1/freight/quotes/{q['id']}/withdraw", headers=uh("fb")).status_code == 404
    assert client.get(f"/v1/freight/quotes/{q['id']}", headers=uh("fb")).status_code == 404
    assert client.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("fa")).status_code == 404
    assert client.get(f"/v1/freight/requests/{req['id']}/quotes", headers=uh("fb")).status_code == 404
    other = make_request(client, user="b2")
    assert client.post(f"/v1/freight/requests/{other['id']}/close", headers=uh("buyer1")).status_code == 404
    assert client.get(f"/v1/freight/requests/{other['id']}", headers=uh("buyer1")).status_code == 404


def test_injection_like_ids_rejected(client):
    assert client.get("/v1/freight/requests/x'%20OR%201=1", headers=uh()).status_code in (404, 422)
    assert client.get("/v1/freight/quotes/..%2f..%2fetc", headers=uh()).status_code in (404, 422)
    assert client.get("/v1/freight/forwarders/" + "a" * 41, headers=uh()).status_code == 422
    assert client.get("/v1/freight/requests/shp_1;DROP", headers=uh()).status_code == 422


def test_route_order_me_vs_id(client):
    make_forwarder(client, "fw")
    assert client.get("/v1/freight/forwarders/me", headers=uh("fw")).json()["status"] == "active"
    assert client.get("/v1/freight/forwarders/me/quotes", headers=uh("fw")).status_code == 200
