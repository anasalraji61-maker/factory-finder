"""QA round 3: no secret / system-prompt leakage across all injection fixtures; input size is capped."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ff_assistant.clients import build_mock_clients
from ff_assistant.config import Settings
from ff_assistant.main import create_app

CASES = json.loads((Path(__file__).parent / "fixtures" / "routing_cases.json").read_text(encoding="utf-8"))["cases"]
INJ = [c for c in CASES if c["category"] == "injection"]
SECRET = "sk-test-SECRET-123456"
TOKEN = "tok-internal-ABCDEF"


def _api():
    s = Settings(clients="mock", FF_INTERNAL_TOKEN=TOKEN, anon_quota_per_day=10000, user_quota_per_day=10000)
    return TestClient(create_app(s, build_mock_clients()))


@pytest.mark.parametrize("case", INJ, ids=[c["id"] for c in INJ])
def test_injection_never_leaks(case, monkeypatch):
    monkeypatch.setenv("FF_LLM_API_KEY", SECRET)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:hunter2@db/x")
    r = _api().post("/v1/assistant/query", json={"text": case["text"]}, headers={"X-Internal-Token": TOKEN, "X-User-Id": "u_demo"})
    assert r.status_code == 200
    blob = (r.text + json.dumps(dict(r.headers))).lower()
    for bad in (SECRET.lower(), TOKEN.lower(), "hunter2", "postgresql://", "you are a", "system prompt:", "ff_internal_token", "ff_llm_api_key"):
        assert bad not in blob, bad
    assert "prompt_injection_ignored" in r.json()["warnings"]


@pytest.mark.parametrize("n", [1001, 5000, 200_000])
def test_oversized_text_rejected(n):
    r = _api().post("/v1/assistant/query", json={"text": "ا" * n}, headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 422


def test_text_at_cap_is_accepted_and_empty_rejected():
    api = _api()
    h = {"X-Internal-Token": TOKEN}
    assert api.post("/v1/assistant/query", json={"text": "ابي بلاستيك " * 83}, headers=h).status_code == 200
    assert api.post("/v1/assistant/query", json={"text": ""}, headers=h).status_code == 422
