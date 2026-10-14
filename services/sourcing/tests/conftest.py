import os

import httpx
import pytest

from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry
from ff_sourcing.clients.trust import MockTrustClient
from ff_sourcing.config import Settings
from ff_sourcing.main import create_app
from ff_sourcing.service import SourcingService

os.environ.setdefault("FF_SOURCING_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.pop("FF_INTERNAL_TOKEN", None)


@pytest.fixture
def service():
    return SourcingService(AdapterRegistry([MockAdapter()]), MockTrustClient())


@pytest.fixture
def app():
    return create_app(
        Settings(trust_mode="mock"), AdapterRegistry([MockAdapter()]), MockTrustClient()
    )


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
