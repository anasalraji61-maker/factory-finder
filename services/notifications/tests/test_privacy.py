import pytest
from fastapi.testclient import TestClient

from ff_notifications.clients.sourcing import MockSourcingClient
from ff_notifications.config import Settings
from ff_notifications.main import create_app

TOK = {"X-Internal-Token": "s3cret"}


@pytest.fixture
def c():
    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", internal_token="s3cret"),
        sourcing=MockSourcingClient([]),
    )
    with TestClient(app) as client:
        yield client


def H(u):
    return {"X-User-Id": u, **TOK}


def seed(c, user):
    assert c.post("/v1/watchlist", headers=H(user), json={"listing_id": "lst_1"}).status_code == 201
    dev = {"platform": "android", "token": f"tok-123{user[-1]}5678", "locale": "ar"}
    assert c.post("/v1/devices", headers=H(user), json=dev).status_code == 201
    prefs = c.put("/v1/notification-prefs", headers=H(user), json={"timezone": "UTC"})
    assert prefs.status_code == 200


def test_requires_internal_token_404(c):
    assert c.post("/v1/internal/users/u1/export").status_code == 404
    bad = {"X-Internal-Token": "bad"}
    assert c.delete("/v1/internal/users/u1/data", headers=bad).status_code == 404


def test_export_then_erase_is_scoped_and_idempotent(c):
    seed(c, "u1")
    seed(c, "u2")
    exp = c.post("/v1/internal/users/u1/export", headers=TOK).json()
    assert exp["service"] == "notifications" and len(exp["data"]["watches"]) == 1
    assert exp["data"]["devices"][0]["token"] == "***5678"  # never the raw delivery token
    d1 = c.delete("/v1/internal/users/u1/data", headers=TOK).json()
    assert d1["status"] == "done" and d1["counts"]["watches"] == 1 and d1["counts"]["devices"] == 1
    d2 = c.delete("/v1/internal/users/u1/data", headers=TOK).json()
    assert d2["status"] == "done" and sum(d2["counts"].values()) == 0
    assert c.get("/v1/watchlist", headers=H("u1")).json()["total"] == 0
    assert c.get("/v1/watchlist", headers=H("u2")).json()["total"] == 1  # other user untouched
