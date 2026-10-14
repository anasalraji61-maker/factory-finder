"""Observability: /ready, request-id propagation, structured JSON request log."""

import json

import pytest
from fastapi.testclient import TestClient

from ff_geo.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def _lines(capsys):
    out = capsys.readouterr().out
    return [json.loads(x) for x in out.splitlines() if x.startswith("{")]


def test_ready_ok(client):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready" and r.json()["service"] == "geo"


def test_request_id_generated_echoed_and_sanitised(client):
    assert len(client.get("/health").headers["x-request-id"]) >= 16
    assert (
        client.get("/health", headers={"X-Request-Id": "abc-123"}).headers["x-request-id"]
        == "abc-123"
    )
    bad = client.get("/health", headers={"X-Request-Id": "evil id\twith spaces"}).headers[
        "x-request-id"
    ]
    assert bad != "evil id\twith spaces" and " " not in bad


def test_one_json_line_without_secrets(client, capsys):
    capsys.readouterr()
    client.get(
        "/health?token=SECRETTOKEN&password=hunter2",
        headers={"Authorization": "Bearer SECRETJWT", "X-Request-Id": "rid-1", "X-User-Id": "u_1"},
    )
    out = capsys.readouterr()
    assert "SECRETTOKEN" not in out.out and "SECRETJWT" not in out.out and "hunter2" not in out.out
    lines = [json.loads(x) for x in out.out.splitlines() if x.startswith("{")]
    assert len(lines) == 1
    e = lines[0]
    assert e["service"] == "geo" and e["request_id"] == "rid-1" and e["method"] == "GET"
    assert e["path"] == "/health" and e["status"] == 200 and e["user_id"] == "u_1"
    assert isinstance(e["duration_ms"], (int, float)) and "ts" in e


def test_unmatched_path_not_logged_raw(client, capsys):
    capsys.readouterr()
    assert client.get("/v1/nope-123456").status_code in (401, 403, 404)
    e = _lines(capsys)[-1]
    assert "123456" not in json.dumps(e) or e["path"] != "/v1/nope-123456"
