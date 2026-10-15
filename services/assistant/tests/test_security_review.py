from ff_assistant import quota as quota_mod
from ff_assistant.quota import DailyQuota


def test_quota_counter_map_is_bounded(monkeypatch):
    monkeypatch.setattr(quota_mod, "MAX_KEYS", 3)
    q = DailyQuota(5, 5, clock=lambda: 1000.0)
    assert all(q.hit(f"u{i}").allowed for i in range(3))
    assert not q.hit("u-new").allowed  # new key beyond the cap: fail closed
    assert q.hit("u0").allowed  # existing keys keep working


def test_overlong_destination_city_is_rejected(api):
    r = api.post("/v1/assistant/query", json={"text": "shipping cost", "destination": {"country_code": "IQ", "city": "x" * 500}})
    assert r.status_code == 422


def _anon_remaining(c, headers):
    r = c.post("/v1/assistant/query", json={"text": "hi"}, headers=headers)
    assert r.status_code == 200
    return int(r.headers["X-Quota-Remaining"])


def _client(**kw):
    from fastapi.testclient import TestClient

    from ff_assistant.clients import build_mock_clients
    from ff_assistant.config import Settings
    from ff_assistant.main import create_app

    return TestClient(create_app(Settings(clients="mock", anon_quota_per_day=5, **kw), build_mock_clients()))


def test_client_ip_header_ignored_without_trust():
    c = _client()  # no token, no trust flag: a spoofed header must not pick the bucket
    a = _anon_remaining(c, {"X-Client-Ip": "1.1.1.1"})
    b = _anon_remaining(c, {"X-Client-Ip": "2.2.2.2"})
    assert b == a - 1  # same peer bucket


def test_client_ip_header_ignored_with_wrong_token_value():
    c = _client(FF_INTERNAL_TOKEN="s3cret")
    r = c.post("/v1/assistant/query", json={"text": "hi"}, headers={"X-Client-Ip": "1.1.1.1", "X-Internal-Token": "bad"})
    assert r.status_code == 401  # never reaches the quota


def test_client_ip_header_keys_quota_with_internal_token():
    c = _client(FF_INTERNAL_TOKEN="s3cret")
    h = {"X-Internal-Token": "s3cret"}
    assert _anon_remaining(c, {**h, "X-Client-Ip": "1.1.1.1"}) == 4
    assert _anon_remaining(c, {**h, "X-Client-Ip": "2.2.2.2"}) == 4  # separate bucket per client
    assert _anon_remaining(c, {**h, "X-Client-Ip": "1.1.1.1"}) == 3


def test_client_ip_header_garbage_falls_back_to_peer():
    c = _client(FF_INTERNAL_TOKEN="s3cret")
    h = {"X-Internal-Token": "s3cret"}
    a = _anon_remaining(c, {**h, "X-Client-Ip": "not-an-ip"})
    b = _anon_remaining(c, {**h, "X-Client-Ip": "1.1.1.1, 2.2.2.2"})
    c2 = _anon_remaining(c, h)
    assert (a, b, c2) == (4, 3, 2)  # all land in the peer bucket


def test_client_ip_header_honoured_with_explicit_trust_flag():
    c = _client(FF_ASSISTANT_TRUST_CLIENT_IP_HEADER="true")
    assert _anon_remaining(c, {"X-Client-Ip": "1.1.1.1"}) == 4
    assert _anon_remaining(c, {"X-Client-Ip": "2.2.2.2"}) == 4
