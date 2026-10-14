import re

import httpx

from ff_gateway.domain.clock import ManualClock
from ff_gateway.domain.rate_limit import (
    FallbackLimiter,
    RateLimiter,
    RedisRateLimiter,
    build_limit_store,
)

REG = {"email": "v@example.com", "password": "password123", "name": "V"}


def _mk(make_client, **kw):
    return make_client(mail_backend="mock", **kw)


def _token(c, i=-1):
    m = c.app.state.mailer.outbox[i]
    return re.search(r"code: (\S+)", m.body).group(1)


def test_default_off_no_mail_and_flag_false(client):
    r = client.post("/v1/auth/register", json=REG)
    assert r.status_code == 201 and r.json()["user"]["email_verified"] is False
    assert client.app.state.mailer.enabled is False


def test_register_verify_flow_and_single_use(make_client):
    c = _mk(make_client)
    tok = c.post("/v1/auth/register", json=REG).json()
    hdr = {"Authorization": f"Bearer {tok['access_token']}"}
    assert len(c.app.state.mailer.outbox) == 1
    t = _token(c)
    assert c.post("/v1/auth/verify-email", json={"token": "x" * 20}).status_code == 400
    assert c.post("/v1/auth/verify-email", json={"token": t}).status_code == 204
    assert c.get("/v1/me", headers=hdr).json()["email_verified"] is True
    assert c.post("/v1/auth/verify-email", json={"token": t}).status_code == 400


def test_token_hashed_at_rest_and_expires(make_client, clock):
    from sqlalchemy import select

    from ff_gateway.db import EmailVerificationToken

    c = _mk(make_client, email_verification_ttl_seconds=60)
    c.post("/v1/auth/register", json=REG)
    t = _token(c)

    async def rows():
        async with c.app.state.sessionmaker() as s:
            return (await s.scalars(select(EmailVerificationToken))).all()

    # TestClient runs the app in another loop; sqlite StaticPool in-memory is shared, query via portal
    rs = c.portal.call(rows)
    assert rs and all(r.token_hash != t and len(r.token_hash) == 64 for r in rs)
    clock.advance(61)
    assert c.post("/v1/auth/verify-email", json={"token": t}).status_code == 400


def test_resend_no_enumeration_and_throttle(make_client):
    c = _mk(make_client)
    c.post("/v1/auth/register", json=REG)
    n = len(c.app.state.mailer.outbox)
    unknown = c.post("/v1/auth/resend-verification", json={"email": "nobody@example.com"})
    known = c.post("/v1/auth/resend-verification", json={"email": REG["email"]})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    assert len(c.app.state.mailer.outbox) == n + 1  # known sent, unknown not
    c.post("/v1/auth/resend-verification", json={"email": REG["email"]})
    assert len(c.app.state.mailer.outbox) == n + 1  # throttled silently
    t = _token(c)  # latest token works; the older one was invalidated
    assert c.post("/v1/auth/verify-email", json={"token": t}).status_code == 204
    c.app.state.limiter._hits.clear()
    c.post("/v1/auth/resend-verification", json={"email": REG["email"]})
    assert len(c.app.state.mailer.outbox) == n + 1  # already verified: nothing sent


def test_email_change_resets_verification(make_client):
    c = _mk(make_client)
    tok = c.post("/v1/auth/register", json=REG).json()
    hdr = {"Authorization": f"Bearer {tok['access_token']}"}
    old = _token(c)
    c.post("/v1/auth/verify-email", json={"token": old})
    r = c.patch("/v1/me", json={"email": "new@example.com"}, headers=hdr)
    assert r.json()["email_verified"] is False
    assert c.app.state.mailer.outbox[-1].to == "new@example.com"


def test_require_verified_gates_sensitive_actions(make_client, mock_upstream):
    c = _mk(make_client, require_email_verified=True)
    tok = c.post("/v1/auth/register", json=REG).json()
    hdr = {"Authorization": f"Bearer {tok['access_token']}"}
    base = c.app.state.settings.upstream_map()
    pay = mock_upstream.post(base["payments"].rstrip("/") + "/v1/invoices").mock(return_value=httpx.Response(201, json={}))
    my = mock_upstream.post(base["sourcing"].rstrip("/") + "/v1/my/listings").mock(return_value=httpx.Response(201, json={}))
    assert c.post("/v1/invoices", json={}, headers=hdr).status_code == 403
    assert c.post("/v1/my/listings", json={}, headers=hdr).json()["error"]["code"] == "email_not_verified"
    assert c.patch("/v1/me", json={"supplier_id": "sup_abc"}, headers=hdr).status_code == 403
    assert c.patch("/v1/me", json={"name": "ok"}, headers=hdr).status_code == 200  # non-sensitive
    assert not pay.called and not my.called
    c.post("/v1/auth/verify-email", json={"token": _token(c)})
    assert c.post("/v1/invoices", json={}, headers=hdr).status_code == 201
    assert c.post("/v1/my/listings", json={}, headers=hdr).status_code == 201
    assert c.patch("/v1/me", json={"supplier_id": "sup_abc"}, headers=hdr).status_code == 200


def test_default_does_not_gate(client, auth, hdr, mock_upstream):
    base = client.app.state.settings.upstream_map()["payments"].rstrip("/")
    mock_upstream.post(base + "/v1/invoices").mock(return_value=httpx.Response(201, json={}))
    assert client.post("/v1/invoices", json={}, headers=hdr).status_code == 201


# ---- rate-limit store ----
class FakeRedis:
    def __init__(self, fail=False):
        self.d, self.ttls, self.fail = {}, {}, fail

    def _chk(self):
        if self.fail:
            raise ConnectionError("down")

    async def incr(self, k):
        self._chk()
        self.d[k] = self.d.get(k, 0) + 1
        self.ttls.setdefault(k, -1)
        return self.d[k]

    async def expire(self, k, s):
        self.ttls[k] = s

    async def ttl(self, k):
        self._chk()
        return self.ttls.get(k, -2)

    async def get(self, k):
        self._chk()
        return self.d.get(k)


async def test_redis_limiter_counts_and_blocks():
    lim = RedisRateLimiter(FakeRedis())
    assert [await lim.check("a", 2) for _ in range(2)] == [None, None]
    assert await lim.check("a", 2) is not None
    assert await lim.blocked("a", 2) is not None
    assert await lim.blocked("zz", 2) is None


async def test_fallback_to_memory_when_redis_down():
    lim = build_limit_store(ManualClock(), 100, redis_client=FakeRedis(fail=True))
    assert isinstance(lim, FallbackLimiter)
    assert await lim.check("k", 1) is None
    assert await lim.check("k", 1) is not None  # memory enforces


def test_unavailable_redis_url_falls_back_to_memory(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "redis", None)
    monkeypatch.setitem(sys.modules, "redis.asyncio", None)
    assert isinstance(build_limit_store(ManualClock(), 10, redis_url="redis://x:1/0"), RateLimiter)


def test_app_uses_injected_redis_for_limits():
    fake = FakeRedis()
    from fastapi.testclient import TestClient

    from ff_gateway.config import Settings
    from ff_gateway.main import create_app

    s = Settings(jwt_secret="x" * 32, database_url="sqlite+aiosqlite://", bcrypt_rounds=4, home_client="mock", auth_rate_limit_per_minute=2)
    with TestClient(create_app(s, redis_client=fake)) as t:
        codes = [t.post("/v1/auth/login", json={"email": "a@b.co", "password": "x"}).status_code for _ in range(4)]
    assert 429 in codes and any(k.startswith("ff:gw:rl:auth:") for k in fake.d)
