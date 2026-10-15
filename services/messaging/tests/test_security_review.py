from fastapi.testclient import TestClient

from ff_messaging.config import Settings
from ff_messaging.main import create_app


def make_client(**overrides) -> TestClient:
    return TestClient(create_app(Settings(database_url="sqlite+aiosqlite:///:memory:", **overrides)))


def test_new_conversations_are_rate_limited_but_existing_ones_are_not():
    with make_client(conversation_create_limit=2, conversation_create_window_seconds=60) as c:
        h = {"X-User-Id": "buyer1"}

        def mk(n: str):
            return c.post("/v1/conversations", headers=h, json={
                "participants": [{"user_id": f"sup{n}", "role": "supplier"}],
                "context": {"type": "listing", "ref_id": f"lst_{n}"}})

        assert [mk("1").status_code, mk("2").status_code] == [201, 201]
        assert mk("1").status_code == 200  # dedupe hit: no budget spent
        r = mk("3")
        assert r.status_code == 429 and "Retry-After" in r.headers


def test_ws_read_frame_with_non_string_message_id_does_not_crash():
    with make_client() as c:
        h = {"X-User-Id": "buyer1"}
        cid = c.post("/v1/conversations", headers=h, json={
            "participants": [{"user_id": "sup1", "role": "supplier"}],
            "context": {"type": "listing", "ref_id": "lst_1"}}).json()["id"]
        with c.websocket_connect(f"/v1/ws/conversations/{cid}", headers=h) as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "read", "message_id": {"x": 1}})
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"


def _conv(c, user, n):
    return c.post("/v1/conversations", headers={"X-User-Id": user}, json={
        "participants": [{"user_id": f"sup{n}", "role": "supplier"}],
        "context": {"type": "listing", "ref_id": f"lst_{n}"}})


def test_conversations_per_user_cap_applies_to_new_only():
    with make_client(max_conversations_per_user=2, conversation_create_limit=100) as c:
        assert [_conv(c, "buyer1", 1).status_code, _conv(c, "buyer1", 2).status_code] == [201, 201]
        assert _conv(c, "buyer1", 1).status_code == 200  # existing thread: free
        r = _conv(c, "buyer1", 3)
        assert r.status_code == 409 and r.json()["error"]["code"] == "conversation_limit_reached"
        assert _conv(c, "buyer2", 3).status_code == 201  # other users unaffected


def test_messages_per_conversation_cap_keeps_idempotent_retries():
    with make_client(max_messages_per_conversation=2, send_rate_limit=100) as c:
        h = {"X-User-Id": "buyer1"}
        cid = _conv(c, "buyer1", 1).json()["id"]
        url = f"/v1/conversations/{cid}/messages"
        assert c.post(url, headers=h, json={"text": "a", "client_message_id": "k1"}).status_code == 201
        assert c.post(url, headers=h, json={"text": "b"}).status_code == 201
        assert c.post(url, headers=h, json={"text": "a", "client_message_id": "k1"}).status_code == 200
        r = c.post(url, headers=h, json={"text": "c"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "conversation_full"


def test_erasure_blanks_text_preview_and_dedupe_but_keeps_counterparty_messages():
    tok = {"X-Internal-Token": "s3cret"}
    with make_client(internal_token="s3cret") as c:
        h = lambda u: {"X-User-Id": u, **tok}  # noqa: E731
        cid = _conv_tok(c, h("buyer1"))
        c.post(f"/v1/conversations/{cid}/messages", headers=h("sup1"), json={"text": "supplier words"})
        c.post(f"/v1/conversations/{cid}/messages", headers=h("buyer1"), json={"text": "my phone 0123", "client_message_id": "k"})
        assert c.delete("/v1/internal/users/buyer1/data", headers=tok).status_code == 200
        thread = c.get(f"/v1/conversations/{cid}/messages", headers=h("sup1")).json()
        texts = [m["text"] for m in thread["items"]]
        assert "supplier words" in texts and "my phone 0123" not in str(thread) and None in texts
        inbox = c.get("/v1/conversations", headers=h("sup1")).json()
        assert "0123" not in str(inbox)


def _conv_tok(c, h):
    return c.post("/v1/conversations", headers=h, json={
        "participants": [{"user_id": "sup1", "role": "supplier"}],
        "context": {"type": "listing", "ref_id": "lst_1"}}).json()["id"]
