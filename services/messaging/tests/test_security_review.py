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
