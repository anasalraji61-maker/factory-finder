from fastapi.testclient import TestClient

from ff_demand.config import Settings
from ff_demand.main import create_app


def test_holds_no_user_data_and_is_internal_only():
    app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:", internal_token="s3cret"))
    with TestClient(app) as c:
        assert c.post("/v1/internal/users/u1/export").status_code == 404
        bad = {"X-Internal-Token": "bad"}
        assert c.delete("/v1/internal/users/u1/data", headers=bad).status_code == 404
        tok = {"X-Internal-Token": "s3cret"}
        exp = c.post("/v1/internal/users/u1/export", headers=tok).json()
        assert exp["data"] == {"holds_user_data": False}
        for _ in range(2):  # idempotent
            assert c.delete("/v1/internal/users/u1/data", headers=tok).json()["status"] == "done"
