import httpx
import pytest

from ff_assistant.clients.base import ClientError
from ff_assistant.clients.http import HttpSourcingClient


def test_health(api):
    assert api.get("/health").json() == {"status": "ok", "service": "assistant", "version": "0.1.0"}


def test_query_endpoint(api):
    r = api.post("/v1/assistant/query", json={"text": "ابي ٥٠٠ كرسي بلاستك من الصين الى اربيل", "locale": "ar"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "search"
    assert body["parsed_query"]["quantity"] == "500"
    assert body["listings"][0]["id"] == "lst_mock_002"
    assert body["quote"]["options"] and body["answer_text"]


def test_validation_error_shape(api):
    r = api.post("/v1/assistant/query", json={"text": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_internal_token_enforced(clients, monkeypatch):
    from fastapi.testclient import TestClient

    from ff_assistant.config import Settings
    from ff_assistant.main import create_app

    c = TestClient(create_app(Settings(clients="mock", FF_INTERNAL_TOKEN="s3cret"), clients))
    assert c.post("/v1/assistant/query", json={"text": "hi"}).status_code == 401
    assert c.post("/v1/assistant/query", json={"text": "hi"}, headers={"X-Internal-Token": "s3cret"}).status_code == 200
    assert c.get("/health").status_code == 200


async def test_http_client_maps_errors_and_params():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params.get("q") == "boom":
            return httpx.Response(500)
        assert req.url.path == "/v1/search" and req.headers["X-Internal-Token"] == "t"
        return httpx.Response(200, json={"items": [], "total": 0, "page": 1, "page_size": 10, "sources": []})

    c = HttpSourcingClient("http://sourcing", 2, "t", httpx.MockTransport(handler))
    assert (await c.search({"q": "x", "kind": None})).total == 0
    with pytest.raises(ClientError):
        await c.search({"q": "boom"})
