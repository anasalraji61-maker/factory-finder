"""Digest e-mail ownership verification: codes, limits, masking, verified-only sending, IDOR."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ff_notifications.adapters.email import MockEmail
from ff_notifications.clients.sourcing import MockSourcingClient
from ff_notifications.config import Settings
from ff_notifications.domain import verification as ver
from ff_notifications.main import create_app

from .test_api import listing
from .test_delivery import Env

H = {"X-User-Id": "u1"}
P = "/v1/notification-prefs"


@pytest.fixture
async def env():
    mock = MockSourcingClient([listing()])
    email = MockEmail()
    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:"),
        sourcing=mock,
        push=None,
        email=email,
    )
    await app.state.service.store.create_all()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        yield Env(app, client, mock, None, email)
    await app.state.service.store.dispose()


async def put(env, email, user="u1"):
    return await env.c.put(P, headers={"X-User-Id": user}, json={"digest_email": email})


async def verify(env, code, user="u1"):
    return await env.c.post(f"{P}/verify-email", headers={"X-User-Id": user}, json={"code": code})


async def get(env, user="u1"):
    return (await env.c.get(P, headers={"X-User-Id": user})).json()


async def test_pending_flow_masking_and_no_code_leak(env):
    r = await put(env, "alice@example.com")
    assert r.status_code == 200
    j = r.json()
    assert j["digest_email"] is None and j["digest_email_verified"] is False
    assert j["digest_email_pending"] == "a***@e***.com"
    (mail,) = env.email.sent
    code = env.last_code()
    assert mail["to"] == "alice@example.com"
    assert "http" not in mail["body"].lower() and "www" not in mail["body"].lower()
    assert "رمز" in mail["body"] and "verification code" in mail["body"].lower()
    assert code not in r.text and code not in (await env.c.get(P, headers=H)).text
    done = await env.verify()
    assert done["digest_email"] == "alice@example.com" and done["digest_email_verified"] is True
    assert done["digest_email_pending"] is None
    assert (await get(env))["digest_email"] == "alice@example.com"


def test_mask_email():
    assert ver.mask_email("alice@example.com") == "a***@e***.com"
    assert ver.mask_email("x@mail.example.co.uk") == "x***@m***.uk"
    assert ver.mask_email(None) is None


async def test_code_format_and_hashing_in_db(env):
    await put(env, "alice@example.com")
    code = env.last_code()
    assert len(code) == 6 and code.isdigit()
    v = await env.svc.store.get_verification("u1")
    assert code not in (v.code_hash, v.salt) and len(v.code_hash) == 64 and len(v.salt) == 32
    assert v.code_hash == ver.hash_code(v.salt, "u1", "alice@example.com", code)
    assert (await verify(env, "12345")).status_code == 422  # not 6 digits
    assert (await verify(env, "abcdef")).status_code == 422


async def test_expiry(env):
    await put(env, "alice@example.com")
    code = env.last_code()
    env.advance(minutes=15, seconds=1)
    r = await verify(env, code)
    assert r.status_code == 422 and r.json()["error"]["code"] == "code_expired"
    assert (await get(env))["digest_email_verified"] is False


async def test_attempts_lock_then_unlock(env):
    await put(env, "alice@example.com")
    code = env.last_code()
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        assert (await verify(env, wrong)).status_code == 422
    r = await verify(env, wrong)  # 5th wrong -> lock
    assert r.status_code == 429 and r.json()["error"]["code"] == "locked"
    assert (await verify(env, code)).status_code == 429  # even the right code is refused
    env.advance(minutes=59)
    assert (await verify(env, code)).status_code == 429
    env.advance(minutes=2)
    assert (await verify(env, code)).status_code in (200, 422)  # lock elapsed (code expired)


async def test_lock_elapsed_correct_code_after_resend(env):
    await put(env, "alice@example.com")
    wrong = "000000" if env.last_code() != "000000" else "111111"
    for _ in range(5):
        await verify(env, wrong)
    env.advance(minutes=61)
    assert (await env.c.post(f"{P}/resend-code", headers=H)).status_code == 200
    assert (await env.verify())["digest_email_verified"] is True


async def test_resend_limit_3_per_hour(env):
    await put(env, "alice@example.com")  # send 1
    for _ in range(2):  # sends 2, 3
        assert (await env.c.post(f"{P}/resend-code", headers=H)).status_code == 200
    r = await env.c.post(f"{P}/resend-code", headers=H)
    assert r.status_code == 429 and r.json()["error"]["code"] == "send_limit"
    assert len(env.email.sent) == 3
    # changing the address is also a send: the limit holds, and nothing changes
    r = await put(env, "mallory@example.org")
    assert r.status_code == 429 and len(env.email.sent) == 3
    assert (await get(env))["digest_email_pending"] == "a***@e***.com"
    env.advance(minutes=61)
    assert (await env.c.post(f"{P}/resend-code", headers=H)).status_code == 200
    assert len(env.email.sent) == 4


async def test_resend_invalidates_previous_code(env):
    await put(env, "alice@example.com")
    old = env.last_code()
    await env.c.post(f"{P}/resend-code", headers=H)
    new = env.last_code()
    if old != new:
        assert (await verify(env, old)).status_code == 422
    assert (await verify(env, new)).status_code == 200


async def test_resend_and_verify_without_pending(env):
    assert (await env.c.post(f"{P}/resend-code", headers=H)).status_code == 409
    assert (await verify(env, "123456")).status_code == 409


async def test_constant_time_compare_used(env, monkeypatch):
    calls = []
    real = ver.hmac.compare_digest

    def spy(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(ver.hmac, "compare_digest", spy)
    await put(env, "alice@example.com")
    await verify(env, "000000")
    assert calls


async def test_changing_address_resets_verification(env):
    await put(env, "alice@example.com")
    await env.verify()
    r = (await put(env, "bob@example.com")).json()
    assert r["digest_email"] is None and r["digest_email_verified"] is False
    assert r["digest_email_pending"] == "b***@e***.com"
    # old code can not verify the new address
    assert env.email.sent[-1]["to"] == "bob@example.com"
    # same verified address again is a no-op (no new mail)
    await env.verify()
    n = len(env.email.sent)
    assert (await put(env, "BOB@example.com")).json()["digest_email_verified"] is True
    assert len(env.email.sent) == n
    # clearing removes everything
    c = (await put(env, "")).json()
    assert c["digest_email"] is None and c["digest_email_pending"] is None


async def test_digest_only_to_verified(env):
    env.now = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)  # 16:00 Baghdad
    await env.prefs(channels={"price_drop": ["in_app", "email"]}, language="en")
    await put(env, "alice@example.com")  # pending only
    code = env.last_code()
    await env.alert()
    env.email.sent.clear()
    assert await env.svc.send_digests() == 0
    assert await env.svc.send_digests() == 0
    assert env.email.sent == []  # unverified: nothing, not even the digest
    await put(env, "alice@example.com")  # same pending: no resend, still unverified
    await env.verify(code=code)
    env.email.sent.clear()
    await env.svc.send_digests()

    assert [m["to"] for m in env.email.sent] == ["alice@example.com"]
    # change address: back to unverified, new address gets no digest
    env.advance(days=1)
    await put(env, "eve@example.com")
    env.email.sent.clear()
    await env.svc.send_digests()
    assert env.email.sent == []


async def test_legacy_unverified_email_in_db_is_never_mailed(env):
    from sqlalchemy import insert

    from ff_notifications.persistence.store import prefs as prefs_t

    doc = {
        "channels": {"price_drop": ["in_app", "email"]},
        "quiet_hours": None,
        "timezone": "Asia/Baghdad",
        "language": "en",
        "email": "legacy@example.com",
    }
    async with env.svc.store.engine.begin() as conn:
        await conn.execute(insert(prefs_t).values(owner_id="u1", doc=doc))
    p = await get(env)
    assert p["digest_email"] is None and p["digest_email_verified"] is False
    assert await env.svc.store.owners_with_email_prefs() == []


async def test_idor_cannot_verify_others_pending(env):
    await put(env, "alice@example.com")
    code = env.last_code()
    # attacker u2 has no pending address: cannot use u1's code
    r = await verify(env, code, user="u2")
    assert r.status_code == 409
    # attacker with own pending address: u1's code does not match (bound to owner + address)
    await put(env, "mallory@example.org", user="u2")
    assert (await verify(env, code, user="u2")).status_code == 422
    assert (await get(env, user="u1"))["digest_email_verified"] is False
    assert (await get(env, user="u2"))["digest_email_verified"] is False
    # u2 failed attempts do not lock u1
    assert (await verify(env, code, user="u1")).status_code == 200
    # u1's verified address is never exposed to u2
    assert "alice" not in (await env.c.get(P, headers={"X-User-Id": "u2"})).text


async def test_provider_off_keeps_pending_without_code():
    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:"),
        sourcing=MockSourcingClient(),
        push=None,
        email=None,
    )
    await app.state.service.store.create_all()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.put(P, headers=H, json={"digest_email": "a@example.com"})
        assert r.json()["digest_email_pending"] == "a***@e***.com"
        assert (await c.post(f"{P}/resend-code", headers=H)).status_code == 409
        v = await c.post(f"{P}/verify-email", headers=H, json={"code": "000000"})
        assert v.status_code == 422
    await app.state.service.store.dispose()


async def test_sent_window_uses_timedelta_constants():
    assert ver.CODE_TTL_SECONDS == 900 and ver.MAX_ATTEMPTS == 5
    assert ver.LOCK_SECONDS == 3600 and ver.MAX_SENDS_PER_HOUR == 3
    assert timedelta(seconds=ver.SEND_WINDOW_SECONDS) == timedelta(hours=1)
