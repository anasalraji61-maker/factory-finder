from fastapi.testclient import TestClient

from ff_assistant.clients import build_mock_clients
from ff_assistant.config import Settings
from ff_assistant.main import create_app

TOK = {"X-Internal-Token": "s3cret"}


def make():
    return TestClient(create_app(Settings(clients="mock", FF_INTERNAL_TOKEN="s3cret"), build_mock_clients()), headers=TOK)


def test_internal_routes_404_without_token():
    c = make()
    assert c.post("/v1/internal/users/u1/export", headers={"X-Internal-Token": "x"}).status_code == 404
    assert c.delete("/v1/internal/users/u1/data", headers={"X-Internal-Token": ""}).status_code == 404


def test_quota_counter_exported_and_erased_idempotently():
    c = make()
    assert c.post("/v1/assistant/query", json={"text": "hi"}, headers={"X-User-Id": "u1"}).status_code == 200
    assert c.post("/v1/internal/users/u1/export").json()["data"]["quota_used_today"] == 1
    assert c.delete("/v1/internal/users/u1/data").json()["counts"] == {"quota_counters_removed": 1}
    assert c.delete("/v1/internal/users/u1/data").json()["counts"] == {"quota_counters_removed": 0}
    assert c.post("/v1/internal/users/u1/export").json()["data"]["quota_used_today"] == 0
