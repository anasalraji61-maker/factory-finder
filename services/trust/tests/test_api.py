import pytest
from fastapi.testclient import TestClient

from ff_trust.config import Settings
from ff_trust.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app(Settings()))


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "service": "trust", "version": "0.1.0"}


def test_get_supplier_shape_and_cache(client):
    r = client.get("/v1/trust/suppliers/sup_demo_gold")
    assert r.status_code == 200
    body = r.json()
    assert body["band"] == "green" and 0 <= body["score"] <= 100
    assert {"key", "impact", "explanation", "explanation_ar"} <= set(body["factors"][0])
    assert client.get("/v1/trust/suppliers/sup_demo_gold").json()["computed_at"] == body["computed_at"]


def test_any_id_works(client):
    assert client.get("/v1/trust/suppliers/sup_cn_001").status_code == 200


def test_evaluate(client):
    r = client.post("/v1/trust/evaluate", json={"sanctions_hit": True})
    assert r.json()["band"] == "red" and r.json()["score"] <= 20
    assert client.post("/v1/trust/evaluate", json={"verified": True}).json()["band"] == "unknown"


def test_evaluate_validation_error_body(client):
    r = client.post("/v1/trust/evaluate", json={"rating_avg": 9})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_batch(client):
    r = client.get("/v1/trust/suppliers:batch", params={"ids": "sup_demo_gold, sup_demo_scam,sup_demo_gold"})
    assert [i["supplier_id"] for i in r.json()["items"]] == ["sup_demo_gold", "sup_demo_scam"]
    assert client.get("/v1/trust/suppliers:batch", params={"ids": " , "}).status_code == 422
    assert client.get("/v1/trust/suppliers:batch", params={"ids": ",".join(f"s{i}" for i in range(60))}).status_code == 422


def test_disabled_real_adapter_503():
    c = TestClient(create_app(Settings(adapter="alibaba")))
    r = c.get("/v1/trust/suppliers/x")
    assert r.status_code == 503 and r.json()["error"]["code"] == "adapter_disabled"


def test_internal_token():
    c = TestClient(create_app(Settings(internal_token="t")))
    assert c.get("/v1/trust/suppliers/a").status_code == 403
    assert c.get("/v1/trust/suppliers/a", headers={"X-Internal-Token": "t"}).status_code == 200
