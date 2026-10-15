from fastapi.testclient import TestClient

from ff_trust.config import Settings
from ff_trust.main import create_app

TOK = {"X-Internal-Token": "s3cret"}


def client():
    return TestClient(create_app(Settings(internal_token="s3cret")), headers=TOK)


def test_internal_routes_404_for_non_internal():
    with client() as c:
        assert c.post("/v1/internal/users/u1/export", headers={"X-Internal-Token": "x"}).status_code == 404
        assert c.delete("/v1/internal/users/u1/data", headers={"X-Internal-Token": ""}).status_code == 404


def test_reports_exported_then_anonymized_idempotently():
    with client() as c:
        for u in ("u1", "u2"):
            assert c.post("/v1/trust/suppliers/sup_demo_gold/report", json={"type": "fraud", "text": "never shipped"}, headers={"X-User-Id": u}).status_code == 201
        assert len(c.post("/v1/internal/users/u1/export").json()["data"]["reports"]) == 1
        assert c.delete("/v1/internal/users/u1/data").json()["counts"] == {"reports_anonymized": 1}
        assert c.delete("/v1/internal/users/u1/data").json()["counts"] == {"reports_anonymized": 0}
        assert c.post("/v1/internal/users/u1/export").json()["data"]["reports"] == []
        assert len(c.post("/v1/internal/users/u2/export").json()["data"]["reports"]) == 1
