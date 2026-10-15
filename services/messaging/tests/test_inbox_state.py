"""Unread totals, read pointer, mute/archive, blocking."""

from concurrent.futures import ThreadPoolExecutor

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
        json={"participants": [{"user_id": other, "role": "supplier"}], "context": {"type": "listing", "ref_id": ref}},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.fixture
def client():
    with make_client(send_rate_limit=1000) as c:
        yield c


def send(c, cid, who, text="hi"):
    r = c.post(f"/v1/conversations/{cid}/messages", headers=H(who), json={"text": text})
    assert r.status_code == 201, r.text
    return r.json()


def total(c, who):
    r = c.get("/v1/conversations/unread-total", headers=H(who))
    assert r.status_code == 200
    return r.json()["unread_total"]


def test_unread_total_and_per_conversation(client):
    a = new_conv(client, ref="l1")["id"]
    b = new_conv(client, ref="l2")["id"]
    for _ in range(2):
        send(client, a, "buyer1")
    send(client, b, "buyer1")
    assert total(client, "sup1") == 3
    assert total(client, "buyer1") == 0
    items = {i["id"]: i for i in client.get("/v1/conversations", headers=H("sup1")).json()["items"]}
    assert (items[a]["unread_count"], items[b]["unread_count"]) == (2, 1)
    assert client.get("/v1/conversations/unread-total").status_code == 401


def test_mark_read_idempotent_and_monotonic(client):
    cid = new_conv(client)["id"]
    m = [send(client, cid, "buyer1", f"m{i}") for i in range(3)]
    r = client.post(f"/v1/conversations/{cid}/read", headers=H("sup1"), json={"message_id": m[1]["id"]})
    assert r.json()["last_read_seq"] == m[1]["seq"] and r.json()["unread_count"] == 1
    # older id and repeat never move it back
    for mid in (m[0]["id"], m[1]["id"]):
        r = client.post(f"/v1/conversations/{cid}/read", headers=H("sup1"), json={"message_id": mid})
        assert r.status_code == 200 and r.json()["last_read_seq"] == m[1]["seq"]
    assert total(client, "sup1") == 1
    assert client.post(f"/v1/conversations/{cid}/read", headers=H("sup1")).json()["unread_count"] == 0


def test_mark_read_authz_idor(client):
    cid = new_conv(client)["id"]
    other = new_conv(client, ref="l9", me="buyer2", other="sup2")
    m = send(client, other["id"], "buyer2")
    send(client, cid, "buyer1")
    # intruder cannot read, and a message id from another conversation is not found
    assert client.post(f"/v1/conversations/{cid}/read", headers=H("buyer2")).status_code == 403
    r = client.post(f"/v1/conversations/{cid}/read", headers=H("sup1"), json={"message_id": m["id"]})
    assert r.status_code == 404
    assert total(client, "sup1") == 1
    # preferences: non participant
    r = client.put(f"/v1/conversations/{cid}/preferences", headers=H("buyer2"), json={"muted": True})
    assert r.status_code == 403
    assert client.get(f"/v1/conversations/{cid}", headers=H("sup1")).json()["muted"] is False


def test_concurrent_mark_read_is_monotonic(client):
    cid = new_conv(client)["id"]
    m = [send(client, cid, "buyer1", f"m{i}") for i in range(6)]

    def go(i):
        return client.post(
            f"/v1/conversations/{cid}/read", headers=H("sup1"), json={"message_id": m[i]["id"]}
        ).status_code

    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(go, [5, 0, 3, 1, 5, 2, 4, 0]))
    assert set(codes) == {200}
    assert client.post(f"/v1/conversations/{cid}/read", headers=H("sup1"), json={"message_id": m[0]["id"]}).json()[
        "last_read_seq"
    ] == m[5]["seq"]
    assert total(client, "sup1") == 0


def test_concurrent_sends_keep_unread_exact(client):
    cid = new_conv(client)["id"]

    def go(i):
        return client.post(
            f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": f"c{i}"}
        ).status_code

    with ThreadPoolExecutor(6) as ex:
        assert set(ex.map(go, range(12))) == {201}
    assert total(client, "sup1") == 12


def test_ws_read_receipt_event_only_when_moved(client):
    cid = new_conv(client)["id"]
    m = send(client, cid, "buyer1")
    with client.websocket_connect(f"/v1/ws/conversations/{cid}?user_id=buyer1") as ws:
        assert ws.receive_json()["type"] == "ready"
        client.post(f"/v1/conversations/{cid}/read", headers=H("sup1"), json={"message_id": m["id"]})
        ev = ws.receive_json()
        assert ev["type"] == "read.updated" and ev["read"]["user_id"] == "sup1"
        assert ev["read"]["last_read_seq"] == m["seq"]
        client.post(f"/v1/conversations/{cid}/read", headers=H("sup1"), json={"message_id": m["id"]})
        send(client, cid, "sup1", "next")
        assert ws.receive_json()["type"] == "message.created"  # no duplicate read.updated before it


def test_mute_and_archive_are_private_and_idempotent(client):
    cid = new_conv(client)["id"]
    send(client, cid, "buyer1")
    for _ in range(2):
        r = client.put(
            f"/v1/conversations/{cid}/preferences", headers=H("sup1"), json={"muted": True}
        )
        assert r.json() == {"conversation_id": cid, "muted": True, "archived": False}
    assert total(client, "sup1") == 0  # muted excluded from badge
    own = client.get("/v1/conversations", headers=H("sup1")).json()["items"][0]
    assert own["muted"] is True and own["unread_count"] == 1
    theirs = client.get(f"/v1/conversations/{cid}", headers=H("buyer1")).json()
    assert theirs["muted"] is False and theirs["archived"] is False
    # archive hides from default list for the archiver only
    client.put(f"/v1/conversations/{cid}/preferences", headers=H("sup1"), json={"archived": True})
    assert client.get("/v1/conversations", headers=H("sup1")).json()["total"] == 0
    assert client.get("/v1/conversations?archived=true", headers=H("sup1")).json()["total"] == 1
    assert client.get("/v1/conversations", headers=H("buyer1")).json()["total"] == 1
    # new message resurfaces it; the sender's own flags are untouched
    send(client, cid, "buyer1", "again")
    assert client.get("/v1/conversations", headers=H("sup1")).json()["total"] == 1
    assert client.put(
        f"/v1/conversations/{cid}/preferences", headers=H("sup1"), json={"x": 1}
    ).status_code == 422


def test_block_hides_thread_and_rejects_neutrally(client):
    cid = new_conv(client)["id"]
    send(client, cid, "buyer1", "before")
    assert client.put("/v1/blocks/buyer1", headers=H("sup1")).status_code == 204
    assert client.put("/v1/blocks/buyer1", headers=H("sup1")).status_code == 204  # idempotent
    # hidden from the blocker everywhere
    assert client.get("/v1/conversations", headers=H("sup1")).json()["total"] == 0
    assert total(client, "sup1") == 0
    assert client.get(f"/v1/conversations/{cid}", headers=H("sup1")).status_code == 404
    assert client.get(f"/v1/conversations/{cid}/messages", headers=H("sup1")).status_code == 404
    # blocked user's send looks exactly like an unknown conversation
    r = client.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": "x"})
    ghost = client.post("/v1/conversations/conv_nope/messages", headers=H("buyer1"), json={"text": "x"})
    assert r.status_code == ghost.status_code == 404
    assert r.json()["error"]["code"] == ghost.json()["error"]["code"]
    assert r.json()["error"]["message"] == ghost.json()["error"]["message"]
    # blocked user cannot start a new thread either
    n = client.post(
        "/v1/conversations",
        headers=H("buyer1"),
        json={"participants": [{"user_id": "sup1"}], "context": {"type": "listing", "ref_id": "lst_77"}},
    )
    assert n.status_code == 404
    # blocker sees only their own list
    assert client.get("/v1/blocks", headers=H("sup1")).json()["items"][0]["user_id"] == "buyer1"
    assert client.get("/v1/blocks", headers=H("buyer1")).json()["items"] == []
    # unblock restores
    assert client.delete("/v1/blocks/buyer1", headers=H("sup1")).status_code == 204
    assert client.get(f"/v1/conversations/{cid}", headers=H("sup1")).status_code == 200
    send(client, cid, "buyer1", "after")


def test_block_validation_and_isolation(client):
    assert client.put("/v1/blocks/sup1", headers=H("sup1")).status_code == 422
    assert client.put("/v1/blocks/usr_support", headers=H("sup1")).status_code == 422
    cid = new_conv(client)["id"]
    # buyer1 blocking sup1 does not affect a third party's threads
    client.put("/v1/blocks/sup1", headers=H("buyer1"))
    cid2 = new_conv(client, me="buyer2", other="sup1", ref="l5")["id"]
    send(client, cid2, "buyer2")
    assert total(client, "sup1") == 1
    # blocker cannot open a new thread with the person they blocked
    r = client.post(
        "/v1/conversations",
        headers=H("buyer1"),
        json={"participants": [{"user_id": "sup1"}], "context": {"type": "listing", "ref_id": "lst_88"}},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "user_blocked"
    assert client.get(f"/v1/conversations/{cid}", headers=H("buyer1")).status_code == 404


def test_supplier_owner_block_applies_to_supplier_identity(client):
    cid = new_conv(client, me="buyer1", other="sup_acme", ref="l3")["id"]
    sup = {"X-User-Id": "owner1", "X-Supplier-Id": "sup_acme"}
    assert client.put("/v1/blocks/buyer1", headers=sup).status_code == 204
    r = client.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": "x"})
    assert r.status_code == 404
    assert client.get(f"/v1/conversations/{cid}", headers=sup).status_code == 404
    assert client.delete("/v1/blocks/buyer1", headers=sup).status_code == 204
    assert client.get(f"/v1/conversations/{cid}", headers=sup).status_code == 200
