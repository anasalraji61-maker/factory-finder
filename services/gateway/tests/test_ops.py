"""Ops hardening: trustworthy client IP, bounded limiter, per-user write limits, /ready, logs."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from ff_gateway.config import Settings
from ff_gateway.domain.client_ip import client_ip, parse_networks
from ff_gateway.domain.clock import ManualClock
from ff_gateway.domain.rate_limit import RateLimiter
from ff_gateway.main import create_app

NETS = parse_networks("10.0.0.0/8, 192.168.1.1")


def test_xff_ignored_from_untrusted_peer():
    assert client_ip("203.0.113.9", "1.2.3.4", NETS) == "203.0.113.9"
    assert client_ip("203.0.113.9", "1.2.3.4", []) == "203.0.113.9"


def test_xff_honoured_from_trusted_peer_rightmost_untrusted():
    assert client_ip("10.0.0.5", "198.51.100.7", NETS) == "198.51.100.7"
    # client-forged left entries are ignored; the last non-proxy hop wins
    assert client_ip("10.0.0.5", "6.6.6.6, 198.51.100.7, 10.1.1.1", NETS) == "198.51.100.7"
    assert client_ip("10.0.0.5", "10.2.2.2, 10.1.1.1", NETS) == "10.2.2.2"


def test_xff_malformed_or_missing_falls_back_to_peer():
    assert client_ip("10.0.0.5", "not-an-ip", NETS) == "10.0.0.5"
    assert client_ip("10.0.0.5", None, NETS) == "10.0.0.5"
    assert client_ip("10.0.0.5", "1.1.1.1, garbage", NETS) == "10.0.0.5"
    assert client_ip(None, "1.1.1.1", NETS) == "unknown"


def test_bad_cidr_fails_at_startup():
    with pytest.raises(ValueError):
        parse_networks("10.0.0.0/8, nonsense")


def test_limiter_memory_is_bounded_and_expired_keys_swept():
    clock = ManualClock()
    lim = RateLimiter(clock, max_keys=3)
    for i in range(10):
        assert lim.check(f"k{i}", 5) is None
        assert len(lim) <= 3
    clock.advance(61)
    assert lim.check("fresh", 5) is None
    assert len(lim) == 1  # expired windows swept


def test_limiter_still_limits_within_window():
    lim = RateLimiter(ManualClock(), max_keys=10)
    assert [lim.check("a", 2) for _ in range(3)][:2] == [None, None]
    assert lim.check("a", 2) is not None
    assert lim.check("b", 2) is None


def _app(client=("203.0.113.9", 5000), **kw):
    s = Settings(
        jwt_secret="test-secret-test-secret-test-secret", database_url="sqlite+aiosqlite://",
        bcrypt_rounds=4, home_client="mock", **kw,
    )  # fmt: skip
    return TestClient(
        create_app(s, clock=ManualClock(), http_client=httpx.AsyncClient()), client=client
    )


def test_spoofed_xff_cannot_evade_limit_when_peer_untrusted():
    with _app(rate_limit_per_minute=2, trusted_proxies="10.0.0.0/8") as c:
        codes = [
            c.get("/v1/nothing", headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code
            for i in range(4)
        ]
    assert codes == [404, 404, 429, 429]


def test_xff_separates_clients_behind_trusted_proxy():
    with _app(client=("10.0.0.5", 1), rate_limit_per_minute=1, trusted_proxies="10.0.0.0/8") as c:
        a = {"X-Forwarded-For": "198.51.100.1"}
        b = {"X-Forwarded-For": "198.51.100.2"}
        assert c.get("/v1/nothing", headers=a).status_code == 404
        assert c.get("/v1/nothing", headers=a).status_code == 429
        assert c.get("/v1/nothing", headers=b).status_code == 404


def test_without_trusted_proxies_everyone_behind_proxy_shares_peer():
    with _app(client=("10.0.0.5", 1), rate_limit_per_minute=1) as c:
        assert c.get("/v1/nothing", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 404
        assert c.get("/v1/nothing", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429


def _register(c, email):
    r = c.post("/v1/auth/register", json={"email": email, "password": "password123", "name": "N"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_per_user_write_limit(mock_upstream):
    route = mock_upstream.post("http://localhost:8105/v1/requests").mock(
        return_value=httpx.Response(201, json={"id": "r"})
    )
    mock_upstream.get("http://localhost:8105/v1/requests").mock(
        return_value=httpx.Response(200, json=[])
    )
    with _app(user_write_rate_limit_per_minute=2) as c:
        h1, h2 = _register(c, "a@example.com"), _register(c, "b@example.com")
        codes = [
            c.post("/v1/requests", json={"title": "t"}, headers=h1).status_code for _ in range(3)
        ]
        assert codes == [201, 201, 429]
        assert route.call_count == 2
        # reads are not user-limited, and another user keeps their own budget
        assert c.get("/v1/requests", headers=h1).status_code == 200
        assert c.post("/v1/requests", json={"title": "t"}, headers=h2).status_code == 201
        # an anonymous/invalid token is not counted per user (route answers 401)
        bad = {"Authorization": "Bearer nope"}
        assert c.post("/v1/requests", json={}, headers=bad).status_code == 401


def test_per_user_limit_disabled_with_zero(mock_upstream):
    mock_upstream.post("http://localhost:8105/v1/requests").mock(
        return_value=httpx.Response(201, json={})
    )
    with _app(user_write_rate_limit_per_minute=0) as c:
        h = _register(c, "z@example.com")
        assert all(c.post("/v1/requests", json={}, headers=h).status_code == 201 for _ in range(5))


def _mock_health(m, down=()):
    for name, port in zip(
        ["sourcing", "logistics", "geo", "trust", "rfq", "messaging", "tracking", "notifications", "assistant", "demand"],
        range(8101, 8111), strict=True,
    ):  # fmt: skip
        r = m.get(f"http://localhost:{port}/health")
        r.mock(return_value=httpx.Response(503 if name in down else 200, json={}))


def test_ready_reports_upstream_booleans_without_urls(mock_upstream):
    _mock_health(mock_upstream, down=("trust",))
    with _app() as c:
        r = c.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded" and body["checks"] == {"database": True}
    assert body["upstreams"]["trust"] is False and body["upstreams"]["rfq"] is True
    assert set(body["upstreams"]) >= {"sourcing", "demand", "assistant"}
    assert "localhost" not in r.text and "http" not in r.text


def test_ready_ok_when_all_up(mock_upstream):
    _mock_health(mock_upstream)
    with _app() as c:
        assert c.get("/ready").json()["status"] == "ready"


def test_ready_503_when_database_down(mock_upstream, monkeypatch):
    _mock_health(mock_upstream)

    async def down(_e):
        return False

    monkeypatch.setattr("ff_gateway.main.db_ready", down)
    with _app() as c:
        r = c.get("/ready")
        assert r.status_code == 503 and r.json()["status"] == "unavailable"
        assert c.get("/health").status_code == 200


def test_request_id_forwarded_and_logged_without_secrets(mock_upstream, capsys):
    route = mock_upstream.post("http://localhost:8105/v1/requests").mock(
        return_value=httpx.Response(201, json={})
    )
    with _app() as c:
        h = _register(c, "log@example.com")
        capsys.readouterr()
        c.post(
            "/v1/requests?token=SECRETQ",
            json={"title": "t"},
            headers={**h, "X-Request-Id": "rid-42"},
        )
        c.get("/health", headers={"X-User-Id": "spoofed"})
        gen = c.get("/v1/nothing")
    assert route.calls.last.request.headers["x-request-id"] == "rid-42"
    assert len(gen.headers["x-request-id"]) >= 16
    out = capsys.readouterr().out
    assert "SECRETQ" not in out and "Bearer" not in out and h["Authorization"].split()[1] not in out
    lines = [json.loads(x) for x in out.splitlines() if x.startswith("{")]
    post = next(x for x in lines if x["method"] == "POST")
    assert post["request_id"] == "rid-42" and post["status"] == 201
    assert post["path"] == "/v1/requests/*" and post["user_id"].startswith("usr_")
    assert (
        next(x for x in lines if x["path"] == "/health").get("user_id") is None
    )  # header spoof ignored
