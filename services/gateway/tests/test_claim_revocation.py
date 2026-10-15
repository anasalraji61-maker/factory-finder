import sqlite3

import pytest
from alembic import command
from alembic.config import Config

from ff_gateway.api.admin import sanitize_reviewer

A = {"X-Admin-Token": "adm-secret"}


@pytest.fixture
def admin(make_client):
    return make_client(admin_token="adm-secret")


def _verified(c, email="u@example.com", sid="sup_a"):
    t = c.post("/v1/auth/register", json={"email": email, "password": "password123", "name": email}).json()
    uid, h = t["user"]["id"], {"Authorization": f"Bearer {t['access_token']}"}
    c.patch("/v1/me", headers=h, json={"supplier_id": sid})
    assert c.post(f"/v1/admin/supplier-claims/{uid}/approve", headers={**A, "X-Reviewer": "alice@corp.com"}).status_code == 200
    return uid, h


def test_sanitize_reviewer():
    assert sanitize_reviewer("alice@corp.com") == "alicecorp.com"
    assert "@" not in sanitize_reviewer("a@b") and sanitize_reviewer(None) == "admin" and sanitize_reviewer("@@") == "admin"
    assert len(sanitize_reviewer("x" * 200)) == 64


def test_revoke_requires_reason_and_verified(admin):
    uid, _ = _verified(admin)
    for body in (None, {}, {"reason": "  "}, {"reason": 5}, {"reason": "x" * 501}):
        assert admin.post(f"/v1/admin/supplier-claims/{uid}/revoke", headers=A, json=body).status_code == 422
    assert admin.get("/v1/admin/supplier-claims?status=verified", headers=A).json()["total"] == 1
    assert admin.post("/v1/admin/supplier-claims/nope/revoke", headers=A, json={"reason": "r"}).status_code == 404
    assert admin.post(f"/v1/admin/supplier-claims/{uid}/revoke", headers={"X-Admin-Token": "bad"}, json={"reason": "r"}).status_code == 401


def test_revoke_drops_supplier_id_immediately_and_audits(admin, mock_upstream):
    uid, h = _verified(admin)
    admin.get("/v1/me", headers=h)  # warm the active cache
    r = admin.post(f"/v1/admin/supplier-claims/{uid}/revoke", headers={**A, "X-Reviewer": "bob"}, json={"reason": "fake docs"})
    assert r.status_code == 200 and r.json()["supplier_claim_status"] == "none" and r.json()["supplier_id"] is None
    me = admin.get("/v1/me", headers=h).json()
    assert me["supplier_claim_status"] == "none" and me["supplier_id"] is None
    assert admin.post(f"/v1/admin/supplier-claims/{uid}/revoke", headers=A, json={"reason": "again"}).status_code == 409
    items = admin.get(f"/v1/admin/supplier-claims/audit?user_id={uid}", headers=A).json()["items"]
    assert [(i["action"], i["reviewer"], i["reason"], i["previous_status"], i["new_status"]) for i in items] == [
        ("revoke", "bob", "fake docs", "verified", "none"),
        ("approve", "alicecorp.com", None, "pending", "verified"),
    ]
    assert admin.get("/v1/admin/supplier-claims/audit", headers={"X-Admin-Token": "bad"}).status_code == 401


def test_proxy_stops_sending_x_supplier_id_after_revoke(admin, mock_upstream):
    import httpx

    route = mock_upstream.get("http://localhost:8106/v1/conversations").mock(return_value=httpx.Response(200, json={}))
    uid, h = _verified(admin)
    admin.get("/v1/conversations", headers=h)
    assert route.calls.last.request.headers["x-supplier-id"] == "sup_a"
    admin.post(f"/v1/admin/supplier-claims/{uid}/revoke", headers=A, json={"reason": "r"})
    admin.get("/v1/conversations", headers=h)
    assert "x-supplier-id" not in route.calls.last.request.headers


def test_reject_and_self_release_are_audited(admin):
    t = admin.post("/v1/auth/register", json={"email": "r@example.com", "password": "password123", "name": "r"}).json()
    uid, h = t["user"]["id"], {"Authorization": f"Bearer {t['access_token']}"}
    admin.patch("/v1/me", headers=h, json={"supplier_id": "sup_r"})
    admin.post(f"/v1/admin/supplier-claims/{uid}/reject", headers=A, json={"reason": "no docs"})
    admin.patch("/v1/me", headers=h, json={"supplier_id": "sup_r"})
    admin.patch("/v1/me", headers=h, json={"supplier_id": None})
    acts = [i["action"] for i in admin.get(f"/v1/admin/supplier-claims/audit?user_id={uid}", headers=A).json()["items"]]
    assert acts == ["self_release", "reject"]


def test_migration_on_sqlite(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/m.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    con = sqlite3.connect(tmp_path / "m.db")
    cols = [r[1] for r in con.execute("PRAGMA table_info(claim_decisions)")]
    assert cols == ["id", "user_id", "supplier_id", "action", "previous_status", "new_status", "reviewer", "reason", "created_at"]
    con.close()
    command.downgrade(cfg, "base")
    assert not [r for r in sqlite3.connect(tmp_path / "m.db").execute("select name from sqlite_master where name='claim_decisions'")]


# --- trust release (best-effort) ---
REL = "http://localhost:8104/v1/admin/trust/verification/suppliers/{}/release"


def _rel_client(make_client):
    return make_client(admin_token="adm-secret", trust_admin_token="trust-secret", internal_token="int-secret")


def test_revoke_and_reject_call_trust_release(make_client, mock_upstream):
    import httpx

    c = _rel_client(make_client)
    route = mock_upstream.post(REL.format("sup_a")).mock(return_value=httpx.Response(200, json={}))
    uid, _ = _verified(c)
    assert c.post(f"/v1/admin/supplier-claims/{uid}/revoke", headers=A, json={"reason": "fake"}).status_code == 200
    req = route.calls.last.request
    assert route.call_count == 1 and req.headers["x-admin-token"] == "trust-secret" and req.headers["x-internal-token"] == "int-secret"
    t = c.post("/v1/auth/register", json={"email": "p@example.com", "password": "password123", "name": "p"}).json()
    h = {"Authorization": f"Bearer {t['access_token']}"}
    r2 = mock_upstream.post(REL.format("sup_p")).mock(return_value=httpx.Response(200, json={}))
    c.patch("/v1/me", headers=h, json={"supplier_id": "sup_p"})
    assert c.post(f"/v1/admin/supplier-claims/{t['user']['id']}/reject", headers=A, json={}).status_code == 200
    assert r2.call_count == 1


def test_self_release_and_change_call_trust_and_failure_never_blocks(make_client, mock_upstream):
    import httpx

    c = _rel_client(make_client)
    ra = mock_upstream.post(REL.format("sup_x")).mock(return_value=httpx.Response(500))
    rb = mock_upstream.post(REL.format("sup_y")).mock(side_effect=httpx.ConnectTimeout("t"))
    t = c.post("/v1/auth/register", json={"email": "s@example.com", "password": "password123", "name": "s"}).json()
    h = {"Authorization": f"Bearer {t['access_token']}"}
    c.patch("/v1/me", headers=h, json={"supplier_id": "sup_x"})
    r = c.patch("/v1/me", headers=h, json={"supplier_id": "sup_y"})  # change: old id released
    assert r.status_code == 200 and r.json()["supplier_id"] == "sup_y" and ra.call_count == 1
    r = c.patch("/v1/me", headers=h, json={"supplier_id": None})
    assert r.status_code == 200 and r.json()["supplier_id"] is None and rb.call_count == 1


def test_no_trust_call_without_admin_token(admin, mock_upstream):
    uid, _ = _verified(admin)
    assert admin.post(f"/v1/admin/supplier-claims/{uid}/revoke", headers=A, json={"reason": "r"}).status_code == 200
    assert not mock_upstream.calls
