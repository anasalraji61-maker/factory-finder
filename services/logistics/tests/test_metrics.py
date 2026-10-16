"""GET /metrics: off by default, token-guarded, bounded labels (obs.py is drift-checked; tests are per service)."""

import pytest
from fastapi.testclient import TestClient

from ff_logistics import obs
from ff_logistics.main import create_app

TOKEN = "t0k3n-metrics"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("FF_ENV", raising=False)
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    obs.reset_metrics()
    return TestClient(create_app())


def test_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("FF_LOGISTICS_METRICS", raising=False)
    assert client.get("/metrics").status_code == 404


def test_enabled_requires_internal_token(client, monkeypatch):
    monkeypatch.setenv("FF_LOGISTICS_METRICS", "1")
    monkeypatch.setenv("FF_INTERNAL_TOKEN", TOKEN)
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"X-Internal-Token": "nope"}).status_code == 401
    assert client.get("/metrics", headers={"X-Internal-Token": TOKEN}).status_code == 200


def test_production_without_token_is_unreachable(client, monkeypatch):
    monkeypatch.setenv("FF_LOGISTICS_METRICS", "1")
    monkeypatch.setenv("FF_ENV", "production")
    assert client.get("/metrics").status_code == 404


def test_counts_use_route_templates_and_status_class(client, monkeypatch):
    monkeypatch.setenv("FF_LOGISTICS_METRICS", "1")
    client.get("/health?secret=abc")
    client.get("/health")
    client.get("/no/such/path/user-42")
    r = client.get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert 'route="/health",status_class="2xx"} 2' in body
    assert "ff_http_request_duration_seconds_bucket" in body and 'le="+Inf"' in body
    assert "ff_process_uptime_seconds" in body
    assert "secret" not in body and "user-42" not in body and "<unmatched>" in body
