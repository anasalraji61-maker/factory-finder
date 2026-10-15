from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ff_feed.config import Settings
from ff_feed.main import create_app

MEDIA = "/v1/media/files/" + "a" * 32 + ".png"
SUP = "sup_acme"
SUP2 = "sup_beta"


class Clock:
    """Deterministic clock: every reading advances 1 ms so ordering is total."""

    def __init__(self):
        self.t = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)

    def __call__(self):
        self.t += timedelta(milliseconds=1)
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


def uh(user="buyer1", supplier=None):
    h = {"X-User-Id": user}
    if supplier:
        h["X-Supplier-Id"] = supplier
    return h


def sh(supplier=SUP, user=None):
    return uh(user or f"owner_{supplier}", supplier)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_client(clock):
    clients = []

    def _make(**kw):
        kw.setdefault("database_url", "sqlite+aiosqlite:///:memory:")
        kw.setdefault("report_min_account_age_seconds", 0)
        c = TestClient(create_app(Settings(**kw), clock=clock))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client(
        rate_posts=0, rate_comments=0, rate_likes=0, rate_follows=0, rate_reports=0
    )


def post(client, text="New CNC machines in stock", supplier=SUP, **extra):
    r = client.post("/v1/feed/posts", headers=sh(supplier), json={"body": text, **extra})
    assert r.status_code == 201, r.text
    return r.json()
