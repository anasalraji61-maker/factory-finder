import pytest
from fastapi.testclient import TestClient

from ff_assistant.clients import build_mock_clients
from ff_assistant.config import Settings
from ff_assistant.main import create_app
from ff_assistant.service import Assistant


@pytest.fixture
def clients():
    return build_mock_clients()


@pytest.fixture
def assistant(clients):
    return Assistant(clients, Settings(clients="mock"))


@pytest.fixture
def api(clients):
    return TestClient(create_app(Settings(clients="mock"), clients))
