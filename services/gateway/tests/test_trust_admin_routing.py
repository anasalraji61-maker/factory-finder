import asyncio

import httpx
import pytest
from sqlalchemy import update

from ff_gateway.db import User

T = dict(host="localhost", port=8104)


def _reg(c, email="t@example.com"):
    r = c.post("/v1/auth/register", json={"email": email, "password": "password123", "name": "T"}).json()
    return {"Authorization": f"Bearer {r['access_token']}"}, r["user"]["id"] if "user" in r else None


def _set_claim(c, supplier_id="sup_1", status="verified"):
    async def go():
        async with c.app.state.sessionmaker() as s:
            await s.execute(update(User).values(supplier_id=supplier_id, supplier_claim_status=status))
            await s.commit()

    asyncio.run(go())


def test_verification_requires_auth_and_verified_claim(make_client, mock_upstream):
    c = make_client(internal_token="int")
    route = mock_upstream.route(host="localhost", port=8104, path="/v1/trust/verification/documents").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    assert c.get("/v1/trust/verification/documents").status_code == 401
    h, _ = _reg(c)
    r = c.get("/v1/trust/verification/documents", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "supplier_claim_required"
    _set_claim(c, status="pending")
    assert c.get("/v1/trust/verification/documents", headers=h).status_code == 403
    assert not route.called
    _set_claim(c)
    r = c.get("/v1/trust/verification/documents", headers={**h, "X-Supplier-Id": "evil", "X-Admin-Token": "x"})
    assert r.status_code == 200
    sent = route.calls.last.request.headers
    assert sent["x-supplier-id"] == "sup_1" and sent["x-internal-token"] == "int"
    assert "x-admin-token" not in sent


def test_verification_post_delete_and_body_limit(make_client, mock_upstream):
    c = make_client(internal_token="int")
    post = mock_upstream.route(host="localhost", port=8104, method="POST", path="/v1/trust/verification/documents").mock(
        return_value=httpx.Response(201, json={"id": "d1"})
    )
    dele = mock_upstream.route(host="localhost", port=8104, method="DELETE", path="/v1/trust/verification/documents/d1").mock(
        return_value=httpx.Response(200, json={"id": "d1"})
    )
    h, _ = _reg(c)
    _set_claim(c)
    assert c.post("/v1/trust/verification/documents", json={"doc_type": "other_certificate"}, headers=h).status_code == 201
    assert post.calls.last.request.headers["x-supplier-id"] == "sup_1"
    assert c.delete("/v1/trust/verification/documents/d1", headers=h).status_code == 200
    big = {"files": ["x" * 70_000]}
    assert c.post("/v1/trust/verification/documents", json=big, headers=h).status_code == 413
    assert post.call_count == 1 and dele.call_count == 1


def test_verification_write_needs_verified_email(make_client, mock_upstream):
    c = make_client(require_email_verified=True)
    mock_upstream.route(host="localhost", port=8104).mock(return_value=httpx.Response(201, json={}))
    h, _ = _reg(c)
    _set_claim(c)
    r = c.post("/v1/trust/verification/documents", json={}, headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_verified"


def test_public_badge_but_other_trust_stays_private(make_client, mock_upstream):
    c = make_client()
    route = mock_upstream.route(host="localhost", port=8104, path="/v1/trust/suppliers/sup_9/verification").mock(
        return_value=httpx.Response(200, json={"level": "basic"})
    )
    assert c.get("/v1/trust/suppliers/sup_9/verification").status_code == 200
    assert "x-supplier-id" not in route.calls.last.request.headers
    assert c.post("/v1/trust/suppliers/sup_9/verification").status_code == 401
    assert c.get("/v1/trust/suppliers/sup_9/history").status_code == 401


def test_trust_admin_passthrough(make_client, mock_upstream):
    c = make_client(admin_token="adm", internal_token="int", trust_admin_token="tr-adm")
    base = "/v1/admin/trust/verification"
    lst = mock_upstream.route(host="localhost", port=8104, path=f"{base}/documents").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    dec = mock_upstream.route(host="localhost", port=8104, path=f"{base}/documents/d1/decision").mock(
        return_value=httpx.Response(200, json={"id": "d1"})
    )
    exp = mock_upstream.route(host="localhost", port=8104, path=f"{base}/documents/d1/expiry").mock(
        return_value=httpx.Response(200, json={"id": "d1"})
    )
    aud = mock_upstream.route(host="localhost", port=8104, path=f"{base}/audit").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    adm = {"X-Admin-Token": "adm"}
    assert c.get(f"{base}/documents").status_code == 401
    assert c.get(f"{base}/documents", headers={"X-Admin-Token": "bad"}).status_code == 401
    assert not lst.called
    r = c.get(f"{base}/documents?status=pending&limit=50", headers={**adm, "X-User-Id": "evil", "X-Supplier-Id": "evil", "X-Reviewer": "evil"})
    assert r.status_code == 200
    h = lst.calls.last.request.headers
    assert h["x-admin-token"] == "tr-adm" and h["x-internal-token"] == "int" and h["x-user-id"] == "admin"
    assert h["x-reviewer"] == "evil" and "x-supplier-id" not in h
    assert c.post(f"{base}/documents/d1/decision", json={"decision": "approve"}, headers=adm).status_code == 200
    assert dec.calls.last.request.content == b'{"decision":"approve"}' or b"approve" in dec.calls.last.request.content
    assert c.put(f"{base}/documents/d1/expiry", json={"expires_on": None}, headers=adm).status_code == 200
    assert c.get(f"{base}/audit?document_id=d1", headers=adm).status_code == 200
    assert exp.called and aud.called


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/v1/admin/trust/verification/documents/d1/decision"),  # wrong method
        ("DELETE", "/v1/admin/trust/verification/documents"),
        ("POST", "/v1/admin/trust/verification/documents/../x/decision"),
        ("POST", "/v1/admin/trust/verification/documents/a%2Fb/decision"),
        ("POST", "/v1/admin/trust/verification/documents/a%25b/decision"),
        ("GET", "/v1/admin/trust/verification/other"),
        ("GET", "/v1/admin/trust/verification/"),
        ("POST", "/v1/admin/trust/verification/documents/" + "x" * 65 + "/decision"),
    ],
)
def test_trust_admin_rejects_unlisted(make_client, mock_upstream, method, path):
    c = make_client(admin_token="adm", trust_admin_token="t")
    route = mock_upstream.route(host="localhost", port=8104).mock(return_value=httpx.Response(200, json={}))
    r = c.request(method, path, headers={"X-Admin-Token": "adm"}, json={} if method != "GET" else None)
    assert r.status_code in (400, 404)
    assert not route.called


def test_admin_passthrough_unset_tokens_and_query(make_client, mock_upstream):
    c = make_client(admin_token="adm")
    adm = {"X-Admin-Token": "adm"}
    for p in ("/v1/admin/trust/verification/documents", "/v1/admin/freight/reports", "/v1/admin/feed/reports"):
        assert c.get(p, headers=adm).status_code == 404  # service token unset
    c = make_client()  # gateway admin token unset
    assert c.get("/v1/admin/freight/reports", headers=adm).status_code == 404
    c = make_client(admin_token="adm", trust_admin_token="t")
    r = c.get("/v1/admin/trust/verification/documents?foo=1", headers=adm)
    assert r.status_code == 422
    assert c.get("/v1/admin/trust/verification/documents?limit=abc", headers=adm).status_code == 422
    assert c.get("/v1/admin/trust/verification/documents?limit=0", headers=adm).status_code == 422
    assert c.get("/v1/admin/trust/verification/documents?status=a%20b", headers=adm).status_code == 422


def test_freight_and_feed_admin_passthrough(make_client, mock_upstream):
    c = make_client(admin_token="adm", internal_token="int", freight_admin_token="fr", feed_admin_token="fd")
    adm = {"X-Admin-Token": "adm", "X-User-Id": "evil"}
    f = mock_upstream.route(host="localhost", port=8114).mock(return_value=httpx.Response(200, json={"items": []}))
    d = mock_upstream.route(host="localhost", port=8113).mock(return_value=httpx.Response(200, json={"items": []}))
    assert c.get("/v1/admin/freight/applications?status=pending&limit=20&cursor=abc", headers=adm).status_code == 200
    assert f.calls.last.request.headers["x-admin-token"] == "fr" and f.calls.last.request.headers["x-user-id"] == "admin"
    assert str(f.calls.last.request.url.path) == "/v1/admin/freight/applications"
    for p in ("applications/a1/approve", "applications/a1/reject", "forwarders/f1/suspend", "forwarders/f1/reinstate", "sweep"):
        assert c.post(f"/v1/admin/freight/{p}", json={"reason": "okay"}, headers=adm).status_code == 200, p
    assert c.get("/v1/admin/freight/reports?target_type=forwarder", headers=adm).status_code == 200
    assert c.get("/v1/admin/freight/nope", headers=adm).status_code == 404
    assert c.post("/v1/admin/freight/applications", json={}, headers=adm).status_code == 404
    assert c.get("/v1/admin/feed/reports?target_type=post", headers=adm).status_code == 200
    assert d.calls.last.request.headers["x-admin-token"] == "fd"
    assert c.post("/v1/admin/feed/posts/p1/hide", json={"reason": "spam"}, headers=adm).status_code == 200
    assert c.post("/v1/admin/feed/comments/c1/restore", headers=adm).status_code == 200
    assert c.get("/v1/admin/feed/posts/p1", headers=adm).status_code == 404
    assert c.get("/v1/admin/feed/reports?bogus=1", headers=adm).status_code == 422
    assert c.get("/v1/admin/freight/reports", headers={"X-Admin-Token": "wrong"}).status_code == 401
