from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ff_tracking.config import Settings
from ff_tracking.main import create_app


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(clock):
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", refresh_min_interval_seconds=60)
    with TestClient(create_app(settings, clock=clock)) as c:
        yield c


H = {"X-User-Id": "usr_a"}
