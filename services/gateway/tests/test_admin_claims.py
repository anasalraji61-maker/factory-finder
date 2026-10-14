import sqlite3

import pytest
from sqlalchemy import text

A = {"X-Admin-Token": "adm-secret"}


@pytest.fixture
def admin(make_client):
    return make_client(admin_token="adm-secret")


def _user(c, email):
    t = c.post(
        "/v1/auth/register", json={"email": email, "password": "password123", "name": email}
    ).json()
    return t["user"]["id"], {"Authorization": f"Bearer {t['access_token']}"}


def test_admin_disabled_when_token_unset(client, hdr):
    for method, path in [
        ("get", "/v1/admin/supplier-claims"),
        ("post", "/v1/admin/supplier-claims/x/approve"),
    ]:
        r = getattr(client, method)(path, headers={"X-Admin-Token": "anything", **hdr})
        assert r.status_code == 404


def test_admin_auth_required(admin):
    uid, h = _user(admin, "u@example.com")
    for headers in ({}, {"X-Admin-Token": "wrong"}, h):  # missing, wrong, ordinary user bearer
        assert admin.get("/v1/admin/supplier-claims", headers=headers).status_code == 401
        assert (
            admin.post(f"/v1/admin/supplier-claims/{uid}/approve", headers=headers).status_code
            == 401
        )
        assert (
            admin.post(f"/v1/admin/supplier-claims/{uid}/reject", headers=headers).status_code
            == 401
        )


def test_claim_flow_approve(admin):
    uid, h = _user(admin, "u@example.com")
    assert admin.get("/v1/me", headers=h).json()["supplier_claim_status"] == "none"
    me = admin.patch("/v1/me", headers=h, json={"supplier_id": "sup_a"}).json()
    assert me["supplier_claim_status"] == "pending"
    # idempotent re-claim keeps pending
    assert (
        admin.patch("/v1/me", headers=h, json={"supplier_id": "sup_a"}).json()[
            "supplier_claim_status"
        ]
        == "pending"
    )
    items = admin.get("/v1/admin/supplier-claims?status=pending", headers=A).json()["items"]
    assert [i["user_id"] for i in items] == [uid] and items[0]["supplier_id"] == "sup_a"
    # pending claim already blocks others (409)
    _, h2 = _user(admin, "v@example.com")
    assert admin.patch("/v1/me", headers=h2, json={"supplier_id": "sup_a"}).status_code == 409
    r = admin.post(f"/v1/admin/supplier-claims/{uid}/approve", headers=A)
    assert r.status_code == 200 and r.json()["supplier_claim_status"] == "verified"
    assert admin.get("/v1/me", headers=h).json()["supplier_claim_status"] == "verified"
    assert admin.get("/v1/admin/supplier-claims", headers=A).json()["items"] == []
    assert (
        len(admin.get("/v1/admin/supplier-claims?status=verified", headers=A).json()["items"]) == 1
    )
    assert (
        admin.post(f"/v1/admin/supplier-claims/{uid}/approve", headers=A).status_code == 409
    )  # not pending
    assert (
        admin.patch("/v1/me", headers=h2, json={"supplier_id": "sup_a"}).status_code == 409
    )  # verified blocks too
    # switching to another id drops verification
    me = admin.patch("/v1/me", headers=h, json={"supplier_id": "sup_b"}).json()
    assert me["supplier_claim_status"] == "pending"
    # release resets
    me = admin.patch("/v1/me", headers=h, json={"supplier_id": None}).json()
    assert me["supplier_id"] is None and me["supplier_claim_status"] == "none"


def test_reject_releases(admin):
    uid, h = _user(admin, "u@example.com")
    admin.patch("/v1/me", headers=h, json={"supplier_id": "sup_a"})
    r = admin.post(f"/v1/admin/supplier-claims/{uid}/reject", headers=A)
    assert (
        r.status_code == 200
        and r.json()["supplier_claim_status"] == "none"
        and r.json()["supplier_id"] is None
    )
    me = admin.get("/v1/me", headers=h).json()
    assert me["supplier_id"] is None and me["supplier_claim_status"] == "none"
    assert admin.post(f"/v1/admin/supplier-claims/{uid}/reject", headers=A).status_code == 409
    assert admin.post("/v1/admin/supplier-claims/usr_nope/approve", headers=A).status_code == 404
    assert admin.get("/v1/admin/supplier-claims?status=bogus", headers=A).status_code == 422
    _, h2 = _user(admin, "v@example.com")
    assert admin.patch("/v1/me", headers=h2, json={"supplier_id": "sup_a"}).status_code == 200


def test_add_column_migration(tmp_path):
    import asyncio

    from ff_gateway.db import create_tables, make_engine

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE users (id VARCHAR(40) PRIMARY KEY, email VARCHAR(320), phone VARCHAR(20), password_hash VARCHAR(100),"
        " name VARCHAR(200), company VARCHAR(200), role VARCHAR(10), default_destination JSON, supplier_id VARCHAR(64),"
        " display_currency VARCHAR(3), language VARCHAR(2), is_active BOOLEAN, created_at DATETIME)"
    )
    con.execute(
        "INSERT INTO users (id, name, supplier_id) VALUES ('u1','A','sup_x'), ('u2','B',NULL)"
    )
    con.commit()
    con.close()

    async def run():
        eng = make_engine(f"sqlite+aiosqlite:///{path}")
        await create_tables(eng)
        await create_tables(eng)  # idempotent
        async with eng.connect() as c:
            rows = (
                await c.execute(text("SELECT id, supplier_claim_status FROM users ORDER BY id"))
            ).all()
        await eng.dispose()
        return rows

    assert [tuple(r) for r in asyncio.run(run())] == [("u1", "pending"), ("u2", "none")]
