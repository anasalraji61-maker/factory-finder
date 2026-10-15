import pytest
from fastapi.testclient import TestClient

from ff_notifications.clients.sourcing import MockSourcingClient
from ff_notifications.config import Settings
from ff_notifications.main import create_app


@pytest.mark.parametrize(
    "bad",
    ["a@b.co\nBcc: v@x.co", "a@b.co\r\n", "a b@c.co", "<a@b.co>", "a@b", "a@@b.co", "a,b@c.co"],
)
def test_prefs_email_rejects_header_injection_and_garbage(bad):
    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:"), sourcing=MockSourcingClient()
    )
    with TestClient(app) as c:
        r = c.put("/v1/notification-prefs", json={"email": bad}, headers={"X-User-Id": "u1"})
        assert r.status_code in (400, 422), bad
        ok = c.put(
            "/v1/notification-prefs",
            json={"email": "user@example.com"},
            headers={"X-User-Id": "u1"},
        )
        assert ok.status_code == 200


def _client():
    return TestClient(
        create_app(
            Settings(database_url="sqlite+aiosqlite:///:memory:"), sourcing=MockSourcingClient()
        )
    )


def test_oversized_search_and_prefs_fields_are_rejected():
    with _client() as c:
        h = {"X-User-Id": "u1"}
        r = c.post("/v1/watchlist", json={"search": {"q": "x", "category": "c" * 5000}}, headers=h)
        assert r.status_code == 422
        r = c.put(
            "/v1/notification-prefs", json={"channels": {f"r{i}": ["push"] for i in range(50)}},
            headers=h,
        )
        assert r.status_code == 422


def test_alert_inbox_is_capped_and_pruned():
    def ev(i):
        return {
            "dedupe_key": f"k{i}", "owner_id": "u1", "shipment_id": "s1",
            "kind": "status_changed", "payload": {"status": "in_transit"},
        }

    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", max_alerts_per_user=3),
        sourcing=MockSourcingClient(),
    )
    with TestClient(app) as c:
        r = c.post("/v1/internal/tracking-events", json={"events": [ev(i) for i in range(6)]})
        assert r.status_code == 200
        r = c.get("/v1/alerts", headers={"X-User-Id": "u1"})
        assert r.json()["total"] == 3


def test_prune_removes_old_alerts_and_finished_deliveries():

    from ff_notifications.service import NotificationService

    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:"), sourcing=MockSourcingClient()
    )
    ev = {
        "dedupe_key": "k", "owner_id": "u1", "shipment_id": "s1",
        "kind": "status_changed", "payload": {"status": "in_transit"},
    }
    with TestClient(app) as c:
        c.post("/v1/internal/tracking-events", json={"events": [ev]})
        service: NotificationService = app.state.service
        from datetime import UTC, datetime, timedelta

        service.clock = lambda: datetime.now(UTC) + timedelta(days=400)
        out = c.portal.call(service.prune)  # type: ignore[union-attr]
        assert out["alerts"] == 1
        assert c.get("/v1/alerts", headers={"X-User-Id": "u1"}).json()["total"] == 0
