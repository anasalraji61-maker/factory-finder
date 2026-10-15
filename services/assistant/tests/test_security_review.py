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
