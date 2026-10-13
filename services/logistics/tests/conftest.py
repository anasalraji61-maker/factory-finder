import os

os.environ.setdefault("FF_LOGISTICS_GEO_PROVIDER", "mock")
os.environ.setdefault("FF_LOGISTICS_FX_PROVIDER", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ff_logistics.adapters.fx import FxService, MockFx  # noqa: E402
from ff_logistics.clients.geo import MockGeo  # noqa: E402
from ff_logistics.domain.engine import Engine  # noqa: E402
from ff_logistics.main import create_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def engine():
    return Engine(MockGeo(), FxService(MockFx()))
