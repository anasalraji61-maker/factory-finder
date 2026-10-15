"""QA wave 4: legacy attachment host pinning, cursor stability, block symmetry, IDOR, ordering."""

from fastapi.testclient import TestClient

from ff_messaging.config import Settings
from ff_messaging.main import create_app


def mk(**kw) -> TestClient:
    return TestClient(create_app(Settings(database_url="sqlite+aiosqlite:///:memory:", **kw)))


def H(u):
    return {"X-User-Id": u}


def conv(c, me="buyer1", other="sup1"):
    r = c.post(
        "/v1/conversations",
        headers=H(me),
        json={"participants": [{"user_id": other, "role": "supplier"}],
              "context": {"type": "listing", "ref_id": "lst_1"}},
    )
    return r.json()["id"]


def legacy(url):
    return {"type": "attachment", "attachment": {"url": url, "mime": "application/pdf", "size": 10}}


def test_legacy_attachment_refuses_arbitrary_hosts_by_default():
    with mk() as c:
        cid = conv(c)
        r = c.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"),
                   json=legacy("https://evil.example.net/a.pdf"))
        assert r.status_code == 422 and r.json()["error"]["code"] == "attachment_url_not_allowed"


def test_legacy_attachment_allowed_on_configured_media_host():
    with mk(media_allowed_hosts=["media.ff.test"]) as c:
        cid = conv(c)
        ok = c.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"),
                    json=legacy("https://media.ff.test/a.pdf"))
        bad = c.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"),
                     json=legacy("https://evil.test/a.pdf"))
        assert ok.status_code == 201 and bad.status_code == 422


def test_block_is_symmetric_and_neutral():
    with mk() as c:
        cid = conv(c)
        assert c.put("/v1/blocks/sup1", headers=H("buyer1")).status_code == 204
        for who in ("buyer1", "sup1"):
            r = c.post(f"/v1/conversations/{cid}/messages", headers=H(who), json={"text": "hi"})
            assert r.status_code == 404
        assert c.get(f"/v1/conversations/{cid}", headers=H("sup1")).status_code == 200  # blocked party only loses send


def test_message_idor_other_conversation_and_message_ids():
    with mk() as c:
        a = conv(c, "buyer1", "sup1")
        b = conv(c, "buyer2", "sup2")
        m = c.post(f"/v1/conversations/{b}/messages", headers=H("buyer2"), json={"text": "x"}).json()
        assert c.get(f"/v1/conversations/{b}/messages", headers=H("buyer1")).status_code == 403
        r = c.post(f"/v1/conversations/{a}/read", headers=H("buyer1"), json={"message_id": m["id"]})
        assert r.status_code == 404  # foreign message id never resolves through own conversation


def test_cursor_pages_stable_under_new_messages_and_read_idempotent():
    with mk() as c:
        cid = conv(c)
        for i in range(7):
            c.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": f"m{i}"})
        p1 = c.get(f"/v1/conversations/{cid}/messages?limit=3", headers=H("sup1")).json()
        c.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": "late"})
        p2 = c.get(f"/v1/conversations/{cid}/messages?limit=3&cursor={p1['next_cursor']}",
                   headers=H("sup1")).json()
        seqs = [m["seq"] for m in p1["items"]] + [m["seq"] for m in p2["items"]]
        assert seqs == sorted(seqs, reverse=True) and len(set(seqs)) == 6
        assert max(m["seq"] for m in p2["items"]) < min(m["seq"] for m in p1["items"])
        r1 = c.post(f"/v1/conversations/{cid}/read", headers=H("sup1")).json()
        r2 = c.post(f"/v1/conversations/{cid}/read", headers=H("sup1")).json()
        assert r1 == r2


def test_ws_reconnect_catches_up_via_rest_in_order():
    with mk() as c:
        cid = conv(c)
        with c.websocket_connect(f"/v1/ws/conversations/{cid}?user_id=sup1") as ws:
            assert ws.receive_json()["type"] == "ready"
        for i in range(3):
            c.post(f"/v1/conversations/{cid}/messages", headers=H("buyer1"), json={"text": f"o{i}"})
        items = c.get(f"/v1/conversations/{cid}/messages", headers=H("sup1")).json()["items"]
        assert [m["text"] for m in reversed(items)] == ["o0", "o1", "o2"]
        assert [m["seq"] for m in reversed(items)] == [1, 2, 3]
