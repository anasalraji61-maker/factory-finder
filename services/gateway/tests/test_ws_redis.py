import pytest

from ff_gateway.domain.clock import ManualClock
from ff_gateway.domain.ws_tickets import (
    FallbackConnectionCounter,
    FallbackTicketStore,
    MemoryConnectionCounter,
    RedisConnectionCounter,
    RedisWsTicketStore,
    WsTicketStore,
    build_ws_stores,
)


class FakeRedis:
    """In-process stand-in for redis.asyncio (strings + counters, no real expiry; records TTLs)."""

    def __init__(self, fail=False):
        self.d, self.ttls, self.fail = {}, {}, fail

    def _chk(self):
        if self.fail:
            raise ConnectionError("down")

    async def set(self, k, v, ex=None):
        self._chk()
        self.d[k], self.ttls[k] = v, ex

    async def getdel(self, k):
        self._chk()
        return self.d.pop(k, None)

    async def incr(self, k):
        self._chk()
        self.d[k] = int(self.d.get(k, 0)) + 1
        return self.d[k]

    async def decr(self, k):
        self._chk()
        self.d[k] = int(self.d.get(k, 0)) - 1
        return self.d[k]

    async def expire(self, k, s):
        self._chk()
        self.ttls[k] = s

    async def delete(self, k):
        self._chk()
        self.d.pop(k, None)


async def test_redis_ticket_single_use_and_ttl():
    r = FakeRedis()
    st = RedisWsTicketStore(r, 30)
    t, ttl = await st.issue("u1")
    assert ttl == 30 and r.ttls["ff:gw:wst:" + t] == 30
    assert await st.consume(t) == "u1"
    assert await st.consume(t) is None  # burned
    assert await st.consume("wst_nope") is None


async def test_two_replicas_share_tickets():
    r = FakeRedis()
    a, b = RedisWsTicketStore(r, 30), RedisWsTicketStore(r, 30)
    t, _ = await a.issue("u1")
    assert await b.consume(t) == "u1"
    assert await a.consume(t) is None


async def test_ticket_fallback_when_redis_down():
    mem = WsTicketStore(ManualClock(), 30, 10)
    st = FallbackTicketStore(RedisWsTicketStore(FakeRedis(fail=True), 30), mem)
    t, _ = await st.issue("u1")
    assert await st.consume(t) == "u1"
    assert await st.consume(t) is None


async def test_connection_counter_cap_and_release():
    r = FakeRedis()
    c = RedisConnectionCounter(r)
    l1, l2 = await c.acquire("u", 2), await c.acquire("u", 2)
    assert l1 and l2 and await c.acquire("u", 2) is None
    assert r.d["ff:gw:wsc:u"] == 2  # refused attempt rolled back
    await l1.release()
    await l1.release()  # idempotent
    assert r.d["ff:gw:wsc:u"] == 1
    l3 = await c.acquire("u", 2)
    assert l3 is not None
    await l2.release()
    await l3.release()
    assert "ff:gw:wsc:u" not in r.d
    assert r.ttls  # safety TTL set


async def test_counter_shared_between_replicas_and_unlimited():
    r = FakeRedis()
    a, b = RedisConnectionCounter(r), RedisConnectionCounter(r)
    assert await a.acquire("u", 1) and await b.acquire("u", 1) is None
    assert [await a.acquire("x", 0) for _ in range(3)] and r.d["ff:gw:wsc:x"] == 3


async def test_counter_fallback_to_memory():
    mem = MemoryConnectionCounter()
    c = FallbackConnectionCounter(RedisConnectionCounter(FakeRedis(fail=True)), mem)
    lease = await c.acquire("u", 1)
    assert lease and mem.counts == {"u": 1} and await c.acquire("u", 1) is None
    await lease.release()
    assert mem.counts == {}


def test_build_defaults_to_memory():
    t, c, mem = build_ws_stores(ManualClock(), 30, 10, None)
    assert isinstance(t, WsTicketStore) and c is mem
    t2, c2, _ = build_ws_stores(ManualClock(), 30, 10, FakeRedis())
    assert isinstance(t2, FallbackTicketStore) and isinstance(c2, FallbackConnectionCounter)


@pytest.fixture
def redis_app():
    import httpx
    from fastapi.testclient import TestClient

    from ff_gateway.config import Settings
    from ff_gateway.main import create_app

    fake = FakeRedis()
    s = Settings(jwt_secret="x" * 32, database_url="sqlite+aiosqlite://", bcrypt_rounds=4, home_client="mock", ws_allow_token_param=False)
    with TestClient(create_app(s, http_client=httpx.AsyncClient(), redis_client=fake)) as t:
        yield t, fake


def test_app_stores_tickets_in_redis(redis_app):
    t, fake = redis_app
    tok = t.post("/v1/auth/register", json={"email": "r@example.com", "password": "password123", "name": "R"}).json()
    ticket = t.post("/v1/ws-ticket", headers={"Authorization": f"Bearer {tok['access_token']}"}).json()["ticket"]
    assert "ff:gw:wst:" + ticket in fake.d
    t.app.state.ws_connect = lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError())
    try:
        with t.websocket_connect(f"/v1/ws/conversations/c1?ticket={ticket}") as w:
            w.receive_text()
    except Exception:
        pass
    assert "ff:gw:wst:" + ticket not in fake.d  # consumed from Redis
    assert not any(k.startswith("ff:gw:wsc:") for k in fake.d)  # slot released after the failed upstream connect


def test_redis_url_alias(monkeypatch):
    from ff_gateway.config import Settings

    monkeypatch.delenv("FF_GATEWAY_REDIS_URL", raising=False)
    monkeypatch.setenv("FF_REDIS_URL", "redis://h:6379/0")
    assert Settings(_env_file=None).redis_url == "redis://h:6379/0"
    monkeypatch.setenv("FF_GATEWAY_REDIS_URL", "redis://g:6379/1")
    assert Settings(_env_file=None).redis_url == "redis://g:6379/1"
