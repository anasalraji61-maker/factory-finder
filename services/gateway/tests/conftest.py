import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from ff_gateway.config import Settings
from ff_gateway.domain.clock import ManualClock
from ff_gateway.main import create_app


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def make_client(clock):
    clients = []

    def _make(**overrides):
        s = Settings(
            jwt_secret="test-secret-test-secret-test-secret", database_url="sqlite+aiosqlite://",
            bcrypt_rounds=4, home_client="mock", **overrides,
        )  # fmt: skip
        c = TestClient(create_app(s, clock=clock, http_client=httpx.AsyncClient()))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def mock_upstream():
    with respx.mock(assert_all_called=False) as m:
        yield m


@pytest.fixture
def auth(client):
    r = client.post("/v1/auth/register", json={"email": "a@example.com", "password": "password123", "name": "Anas"})
    assert r.status_code == 201
    return r.json()


@pytest.fixture
def hdr(auth):
    return {"Authorization": f"Bearer {auth['access_token']}"}
