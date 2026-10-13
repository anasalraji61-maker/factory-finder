import pytest
from fastapi.testclient import TestClient

from ff_messaging.config import Settings
from ff_messaging.main import create_app


def make_client(**overrides) -> TestClient:
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", **overrides)
    return TestClient(create_app(s))


def H(user: str) -> dict:
    return {"X-User-Id": user}


def new_conv(c, me="buyer1", other="sup1", ref="lst_1"):
    r = c.post(
        "/v1/conversations",
        headers=H(me),
        json={
            "participants": [{"user_id": other, "role": "supplier"}],
            "context": {"type": "listing", "ref_id": ref},
        },
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.fixture
def client():
    with make_client() as c:
        yield c


def test_health(client):
    assert client.get("/health").json()["service"] == "messaging"


def test_idempotent_create(client):
    r1 = client.post(
        "/v1/conversations",
        headers=H("buyer1"),
        json={
            "participants": [{"user_id": "sup1"}],
            "context": {"type": "listing", "ref_id": "lst_1"},
        },
    )
    r2 = client.post(
        "/v1/conversations",
        headers=H("sup1"),
        json={
            "participants": [{"user_id": "buyer1", "role": "buyer"}],
            "context": {"type": "listing", "ref_id": "lst_1"},
        },
    )
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r1.json()["id"] == r2.json()["id"]
    other = new_conv(client, ref="lst_2")
    assert other["id"] != r1.json()["id"]


def test_auth_and_access_control(client):
    c = new_conv(client)
    cid = c["id"]
    assert client.get("/v1/conversations").status_code == 401
    assert client.get(f"/v1/conversations/{cid}", headers=H("intruder")).status_code == 403
    assert client.get(f"/v1/conversations/{cid}/messages", headers=H("intruder")).status_code == 403
    assert (
        client.post(
            f"/v1/conversations/{cid}/messages", headers=H("intruder"), json={"text": "x"}
        ).status_code
        == 403
    )
    assert client.post(f"/v1/conversations/{cid}/read", headers=H("intruder")).status_code == 403
    r = client.get("/v1/conversations/conv_nope", headers=H("buyer1"))
    assert r.status_code == 404 and r.json()["error"]["code"] == "conversation_not_found"
    assert (
        client.post("/v1/conversations", headers=H("buyer1"), json={}).json()["error"]["code"]
        == "not_enough_participants"
    )


def test_unread_and_read_receipts(client):
    cid = new_conv(client)["id"]
    for i in range(3):
        assert (
            client.post(
                f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": f"hi {i}"}
            ).status_code
            == 201
        )
    lst = client.get("/v1/conversations", headers=H("sup1")).json()
    assert lst["unread_total"] == 3 and lst["items"][0]["unread_count"] == 3
    assert lst["items"][0]["last_message"]["preview"] == "hi 2"
    assert client.get("/v1/conversations", headers=H("buyer1")).json()["unread_total"] == 0
    msgs = client.get(f"/v1/conversations/{cid}/messages", headers=H("sup1")).json()["items"]
    assert msgs[0]["read_by"] == []
    st = client.post(
        f"/v1/conversations/{cid}/read", headers=H("sup1"), json={"message_id": msgs[1]["id"]}
    ).json()
    assert st["unread_count"] == 1
    assert (
        client.post(f"/v1/conversations/{cid}/read", headers=H("sup1")).json()["unread_count"] == 0
    )
    msgs = client.get(f"/v1/conversations/{cid}/messages", headers=H("buyer1")).json()["items"]
    assert all(m["read_by"] == ["sup1"] for m in msgs)
    assert client.get("/v1/conversations?unread_only=true", headers=H("sup1")).json()["total"] == 0


def test_pagination(client):
    cid = new_conv(client)["id"]
    for i in range(5):
        client.post(
            f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": f"m{i}"}
        )
    p1 = client.get(f"/v1/conversations/{cid}/messages?limit=2", headers=H("sup1")).json()
    assert [m["text"] for m in p1["items"]] == ["m4", "m3"] and p1["has_more"]
    p2 = client.get(
        f"/v1/conversations/{cid}/messages?limit=2&cursor={p1['next_cursor']}", headers=H("sup1")
    ).json()
    assert [m["text"] for m in p2["items"]] == ["m2", "m1"]
    p3 = client.get(
        f"/v1/conversations/{cid}/messages?limit=2&cursor={p2['next_cursor']}", headers=H("sup1")
    ).json()
    assert (
        [m["text"] for m in p3["items"]] == ["m0"]
        and not p3["has_more"]
        and p3["next_cursor"] is None
    )
    bad = client.get(f"/v1/conversations/{cid}/messages?cursor=zzz", headers=H("sup1"))
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_cursor"


def test_client_message_id_idempotent(client):
    cid = new_conv(client)["id"]
    body = {"text": "once", "client_message_id": "abc"}
    a = client.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json=body)
    b = client.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json=body)
    assert (a.status_code, b.status_code) == (201, 200) and a.json()["id"] == b.json()["id"]
    assert (
        len(client.get(f"/v1/conversations/{cid}/messages", headers=H("buyer1")).json()["items"])
        == 1
    )


def test_rate_limit():
    with make_client(send_rate_limit=3, send_rate_window_seconds=60) as c:
        cid = new_conv(c)["id"]
        codes = [
            c.post(
                f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": "x"}
            ).status_code
            for _ in range(4)
        ]
        assert codes == [201, 201, 201, 429]
        r = c.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": "x"})
        assert r.json()["error"]["code"] == "rate_limited" and "Retry-After" in r.headers


def test_abuse_flag_mask_reject():
    with make_client() as c:
        cid = new_conv(c)["id"]
        m = c.post(
            f"/v1/conversations/{cid}/messages",
            headers=H("buyer1"),
            json={"text": "you are a bitch"},
        ).json()
        assert (
            m["flagged"] and m["flags"] == ["abusive_language"] and m["text"] == "you are a bitch"
        )
    with make_client(abuse_action="mask") as c:
        cid = new_conv(c)["id"]
        m = c.post(
            f"/v1/conversations/{cid}/messages",
            headers=H("buyer1"),
            json={"text": "you are a bitch"},
        ).json()
        assert "bitch" not in m["text"] and m["flagged"]
    with make_client(abuse_action="reject") as c:
        cid = new_conv(c)["id"]
        r = c.post(
            f"/v1/conversations/{cid}/messages",
            headers=H("buyer1"),
            json={"text": "you are a bitch"},
        )
        assert r.status_code == 422 and r.json()["error"]["code"] == "message_rejected"


def test_validation(client):
    cid = new_conv(client)["id"]
    assert (
        client.post(
            f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": "  "}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": "x" * 5000}
        ).status_code
        == 422
    )
    r = client.post(
        f"/v1/conversations/{cid}/messages",
        headers=H("buyer1"),
        json={
            "type": "attachment",
            "attachment": {
                "url": "https://cdn.example.com/a.pdf",
                "mime": "application/pdf",
                "size": 100,
            },
        },
    )
    assert r.status_code == 201 and r.json()["attachment"]["mime"] == "application/pdf"
    r = client.post(
        f"/v1/conversations/{cid}/messages",
        headers=H("buyer1"),
        json={
            "type": "attachment",
            "attachment": {
                "url": "http://x.com/a.exe",
                "mime": "application/x-msdownload",
                "size": 1,
            },
        },
    )
    assert r.status_code == 422


def test_websocket_broadcast(client):
    cid = new_conv(client)["id"]
    with client.websocket_connect(f"/v1/ws/conversations/{cid}?user_id=sup1") as ws:
        assert ws.receive_json()["type"] == "ready"
        client.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": "live"})
        evt = ws.receive_json()
        assert evt["type"] == "message.created" and evt["message"]["text"] == "live"
        client.post(f"/v1/conversations/{cid}/read", headers=H("sup1"))
        assert ws.receive_json()["type"] == "read.updated"


def test_websocket_access():
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with make_client() as c:
        cid = new_conv(c)["id"]
        for q, code in (("", 4401), ("?user_id=intruder", 4403)):
            with pytest.raises(WebSocketDisconnect) as ei:
                with c.websocket_connect(f"/v1/ws/conversations/{cid}{q}"):
                    pass
            assert ei.value.code == code


def S(user: str, sup: str | None = None) -> dict:
    h = {"X-User-Id": user}
    if sup:
        h["X-Supplier-Id"] = sup
    return h


def test_supplier_claim_can_answer(client):
    r = client.post(
        "/v1/conversations",
        headers=H("buyer1"),
        json={"supplier_ref": "sup_cn_018", "context": {"type": "listing", "ref_id": "lst_9"}},
    )
    assert r.status_code == 201, r.text
    conv = r.json()
    cid = conv["id"]
    assert conv["supplier_ref"] == "sup_cn_018"
    assert (
        client.post(
            f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": "hi"}
        ).status_code
        == 201
    )

    # claimer (a different user id) sees, reads, answers
    claimer = S("usr_owner", "sup_cn_018")
    lst = client.get("/v1/conversations", headers=claimer).json()
    assert [c["id"] for c in lst["items"]] == [cid] and lst["unread_total"] == 1
    assert lst["items"][0]["unread_count"] == 1
    assert client.get(f"/v1/conversations/{cid}", headers=claimer).status_code == 200
    assert client.get(f"/v1/conversations/{cid}/messages", headers=claimer).status_code == 200
    assert client.post(f"/v1/conversations/{cid}/read", headers=claimer).json()["unread_count"] == 0
    m = client.post(f"/v1/conversations/{cid}/messages", headers=claimer, json={"text": "hello"})
    assert m.status_code == 201 and m.json()["sender_id"] == "sup_cn_018"
    assert (
        client.get("/v1/conversations", headers=H("buyer1")).json()["items"][0]["unread_count"] == 1
    )

    # third parties stay locked out, even claiming another supplier
    for h in (H("intruder"), S("intruder", "sup_other"), S("intruder")):
        assert client.get("/v1/conversations", headers=h).json()["total"] == 0
        assert client.get(f"/v1/conversations/{cid}", headers=h).status_code == 403
        assert client.get(f"/v1/conversations/{cid}/messages", headers=h).status_code == 403
        assert (
            client.post(
                f"/v1/conversations/{cid}/messages", headers=h, json={"text": "x"}
            ).status_code
            == 403
        )
        assert client.post(f"/v1/conversations/{cid}/read", headers=h).status_code == 403
    # malformed / non-supplier header is ignored
    assert (
        client.get(
            f"/v1/conversations/{cid}", headers={**H("intruder"), "X-Supplier-Id": "buyer1"}
        ).status_code
        == 403
    )
