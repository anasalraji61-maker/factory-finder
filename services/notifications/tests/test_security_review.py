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
