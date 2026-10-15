from fastapi.testclient import TestClient

from ff_messaging.config import Settings
from ff_messaging.main import create_app


def make_client(**overrides) -> TestClient:
    return TestClient(create_app(Settings(database_url="sqlite+aiosqlite:///:memory:", **overrides)))


def H(user: str) -> dict:
    return {"X-User-Id": user}


TOK = {"X-Internal-Token": "s3cret"}


def test_privacy_endpoints_hidden_without_token():
    with make_client(internal_token="s3cret") as c:
        assert c.post("/v1/internal/users/buyer1/export").status_code == 404
        assert c.delete("/v1/internal/users/buyer1/data", headers={"X-Internal-Token": "x"}).status_code == 404


def test_export_and_erase_keeps_thread_for_counterparty():
    with make_client(internal_token="s3cret") as c:
        h = lambda u: {**H(u), **TOK}  # noqa: E731
        conv = c.post("/v1/conversations", headers=h("buyer1"), json={
            "participants": [{"user_id": "sup1", "role": "supplier"}],
            "context": {"type": "listing", "ref_id": "lst_1"}}).json()
        cid = conv["id"]
        assert c.post(f"/v1/conversations/{cid}/messages", headers=h("buyer1"), json={"text": "hello from buyer"}).status_code == 201
        assert c.post(f"/v1/conversations/{cid}/messages", headers=h("sup1"), json={"text": "hi buyer"}).status_code == 201
        exp = c.post("/v1/internal/users/buyer1/export", headers=TOK).json()
        assert [m["text"] for m in exp["data"]["messages_sent"]] == ["hello from buyer"]
        assert c.delete("/v1/internal/users/buyer1/data", headers=TOK).json()["counts"]["messages_anonymized"] == 1
        again = c.delete("/v1/internal/users/buyer1/data", headers=TOK).json()
        assert again["status"] == "done" and again["counts"]["messages_anonymized"] == 0
        # counterparty still sees the whole thread, but the buyer id is gone
        thread = c.get(f"/v1/conversations/{cid}/messages", headers=h("sup1")).json()
        assert len(thread["items"]) == 2 and "buyer1" not in str(thread)
        assert c.post("/v1/internal/users/buyer1/export", headers=TOK).json()["data"]["messages_sent"] == []
        assert c.get("/v1/conversations", headers=h("buyer1")).json()["items"] == []
