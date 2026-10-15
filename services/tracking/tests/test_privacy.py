from fastapi.testclient import TestClient

from ff_tracking.config import Settings
from ff_tracking.main import create_app

TOK = {"X-Internal-Token": "s3cret"}
BODY = {"reference_type": "container", "reference": "CSQU3054383"}


def test_export_and_erase_scoped_idempotent_and_hidden():
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", internal_token="s3cret")
    with TestClient(create_app(s), headers=TOK) as c:
        assert c.post("/v1/internal/users/usr_a/export", headers={"X-Internal-Token": "x"}).status_code == 404
        assert c.delete("/v1/internal/users/usr_a/data", headers={"X-Internal-Token": ""}).status_code == 404
        assert c.post("/v1/shipments", json=BODY, headers={"X-User-Id": "usr_a"}).status_code == 201
        assert c.post("/v1/shipments", json=BODY, headers={"X-User-Id": "usr_b"}).status_code == 201
        assert len(c.post("/v1/internal/users/usr_a/export").json()["data"]["shipments"]) == 1
        assert c.delete("/v1/internal/users/usr_a/data").json()["counts"]["shipments_deleted"] == 1
        assert c.delete("/v1/internal/users/usr_a/data").json()["counts"] == {"shipments_deleted": 0, "outbox_deleted": 0}
        assert c.get("/v1/shipments", headers={"X-User-Id": "usr_a"}).json()["total"] == 0
        assert c.get("/v1/shipments", headers={"X-User-Id": "usr_b"}).json()["total"] == 1
