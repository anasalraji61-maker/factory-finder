import httpx

from ff_gateway.domain.circuit_breaker import CircuitBreaker
from ff_gateway.domain.clock import ManualClock


def test_breaker_state_machine():
    clk = ManualClock()
    b = CircuitBreaker("x", clk, 3, 30)
    for _ in range(2):
        assert b.before() is None
        b.failure()
    b.success()  # consecutive: a success resets the count
    for _ in range(2):
        b.failure()
    assert b.state == "closed" and b.before() is None
    b.failure()
    assert b.state == "open" and b.before() == 30
    clk.advance(10)
    assert b.before() == 20
    clk.advance(21)
    assert b.before() is None and b.state == "half_open"  # the probe
    assert b.before() == 1  # others keep failing fast
    b.failure()  # probe failed -> open again, full cooldown
    assert b.state == "open" and b.before() == 30
    clk.advance(31)
    assert b.before() is None
    b.success()
    assert b.state == "closed" and b.before() is None


def test_abort_frees_probe_and_zero_disables():
    clk = ManualClock()
    b = CircuitBreaker("x", clk, 1, 5)
    b.failure()
    clk.advance(6)
    assert b.before() is None
    b.abort()
    assert b.before() is None  # slot free again
    off = CircuitBreaker("y", clk, 0, 5)
    for _ in range(10):
        off.failure()
    assert off.before() is None


def _url(c, name="sourcing"):
    return c.app.state.settings.upstream_map()[name].rstrip("/")


def test_proxy_opens_after_consecutive_failures(make_client, clock, mock_upstream):
    c = make_client(breaker_failure_threshold=3, breaker_cooldown_seconds=30)
    route = mock_upstream.get(_url(c) + "/v1/search").mock(side_effect=httpx.ConnectError("refused"))
    assert [c.get("/v1/search").status_code for _ in range(3)] == [502, 502, 502]
    assert route.call_count == 3
    r = c.get("/v1/search")
    assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_unavailable"
    assert r.json()["error"]["details"]["upstream"] == "sourcing" and 1 <= int(r.headers["Retry-After"]) <= 30
    assert route.call_count == 3  # fast-fail: the fake upstream was not called
    # other upstreams are unaffected
    mock_upstream.get(_url(c, "geo") + "/v1/countries").respond(200, json=[])
    assert c.get("/v1/countries").status_code == 200


def test_proxy_half_open_probe_recovers(make_client, clock, mock_upstream):
    c = make_client(breaker_failure_threshold=2, breaker_cooldown_seconds=30)
    route = mock_upstream.get(_url(c) + "/v1/search").mock(side_effect=httpx.ReadTimeout("slow"))
    assert [c.get("/v1/search").status_code for _ in range(2)] == [504, 504]
    assert c.get("/v1/search").status_code == 503
    clock.advance(31)
    route.mock(side_effect=None, return_value=httpx.Response(200, json={"ok": True}))
    assert c.get("/v1/search").status_code == 200  # probe succeeds -> closed
    assert c.get("/v1/search").status_code == 200
    assert route.call_count == 4


def test_proxy_failed_probe_reopens(make_client, clock, mock_upstream):
    c = make_client(breaker_failure_threshold=1, breaker_cooldown_seconds=10)
    route = mock_upstream.get(_url(c) + "/v1/search").mock(return_value=httpx.Response(503, json={"error": {"code": "x", "message": "m", "details": {}}}))
    assert c.get("/v1/search").status_code == 503  # real upstream 503 passes through and counts
    assert route.call_count == 1
    assert c.get("/v1/search").headers.get("Retry-After")  # breaker answers
    assert route.call_count == 1
    clock.advance(11)
    c.get("/v1/search")  # probe, fails
    assert route.call_count == 2
    r = c.get("/v1/search")
    assert r.status_code == 503 and route.call_count == 2 and r.json()["error"]["details"].get("circuit") == "open"


def test_client_errors_and_500_do_not_trip(make_client, mock_upstream):
    c = make_client(breaker_failure_threshold=2)
    route = mock_upstream.get(_url(c) + "/v1/search").mock(return_value=httpx.Response(500, text="boom"))
    for _ in range(5):
        assert c.get("/v1/search").status_code == 500
    assert route.call_count == 5
    mock_upstream.get(_url(c, "logistics") + "/v1/hs/1").respond(404, json={"error": {"code": "n", "message": "m", "details": {}}})
    assert [c.get("/v1/hs/1").status_code for _ in range(5)] == [404] * 5


def test_breaker_off_with_zero(make_client, mock_upstream):
    c = make_client(breaker_failure_threshold=0)
    route = mock_upstream.get(_url(c) + "/v1/search").mock(side_effect=httpx.ConnectError("x"))
    assert [c.get("/v1/search").status_code for _ in range(8)] == [502] * 8
    assert route.call_count == 8


def test_default_client_has_tight_timeouts_and_pool_limits():
    import asyncio

    from ff_gateway.config import Settings
    from ff_gateway.main import create_app

    s = Settings(jwt_secret="x" * 32, database_url="sqlite+aiosqlite://", upstream_max_connections=7, upstream_max_keepalive_connections=3)
    app = create_app(s)
    http = app.state.http
    assert http.timeout.connect == 3.0 and http.timeout.read == 15.0 and http.timeout.pool == 5.0
    pool = http._transport._pool
    assert pool._max_connections == 7 and pool._max_keepalive_connections == 3
    asyncio.run(http.aclose())
