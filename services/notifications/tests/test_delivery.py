"""Delivery: devices, prefs, quiet hours, retry/backoff, dead letter, idempotency, FCM shape."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ff_notifications.adapters.email import MockEmail
from ff_notifications.adapters.push import FcmPush, MockPush, PushResult
from ff_notifications.clients.sourcing import MockSourcingClient
from ff_notifications.config import Settings
from ff_notifications.domain.delivery import DeliveryStatus
from ff_notifications.domain.models import Device, Locale, Platform
from ff_notifications.main import build_email, build_push, create_app

from .test_api import listing

T0 = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)  # 15:00 Baghdad
TOKEN = "tok-secret-0001"


class Env:
    def __init__(self, app, client, mock, push, email):
        self.app, self.c, self.mock, self.push, self.email = app, client, mock, push, email
        self.svc = app.state.service
        self.now = T0
        self.svc.clock = lambda: self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)

    async def device(self, user="u1", token=TOKEN, locale="en", platform="android"):
        r = await self.c.post(
            "/v1/devices",
            headers={"X-User-Id": user},
            json={"platform": platform, "token": token, "locale": locale},
        )
        assert r.status_code in (200, 201), r.text
        return r.json()

    async def prefs(self, user="u1", **body):
        r = await self.c.put("/v1/notification-prefs", headers={"X-User-Id": user}, json=body)
        assert r.status_code == 200, r.text
        return r.json()

    def last_code(self) -> str:
        import re

        return re.search(r"\b(\d{6})\b", self.email.sent[-1]["body"]).group(1)

    async def verify(self, user="u1", code=None):
        r = await self.c.post(
            "/v1/notification-prefs/verify-email",
            headers={"X-User-Id": user},
            json={"code": code or self.last_code()},
        )
        assert r.status_code == 200, r.text
        return r.json()

    async def alert(self, user="u1"):
        """Create one price_drop alert (baseline then a price drop) and run delivery."""
        r = await self.c.post(
            "/v1/watchlist", headers={"X-User-Id": user}, json={"listing_id": "lst_1"}
        )
        assert r.status_code in (200, 201), r.text
        await self.svc.evaluate_all()
        self.mock.set_price("lst_1", "50")
        return await self.svc.evaluate_all()


@pytest.fixture
async def env():
    mock = MockSourcingClient([listing()])
    push, email = MockPush(), MockEmail()
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        delivery_max_attempts=3,
        delivery_backoff_base_seconds=30,
    )
    app = create_app(s, sourcing=mock, push=push, email=email)
    await app.state.service.store.create_all()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        yield Env(app, client, mock, push, email)
    await app.state.service.store.dispose()


# --------------------------------------------------------------- devices


async def test_device_limit_dedupe_and_token_not_logged(env, capsys):
    first = await env.device(token="tok-00000000")
    assert (await env.device(token="tok-00000000"))["id"] == first["id"]  # dedupe
    for i in range(1, 10):
        await env.device(token=f"tok-{i:08d}")
    r = await env.c.post(
        "/v1/devices",
        headers={"X-User-Id": "u1"},
        json={"platform": "ios", "token": "tok-overflow"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "device_limit"
    assert (await env.device(token="tok-00000000"))["id"] == first["id"]  # existing still ok
    await env.device(user="u2", token="tok-other-user")  # cap is per user
    listed = (await env.c.get("/v1/devices", headers={"X-User-Id": "u1"})).json()["items"]
    assert len(listed) == 10
    assert (
        await env.c.delete(f"/v1/devices/{first['id']}", headers={"X-User-Id": "u1"})
    ).status_code == 204
    await env.device(token="tok-overflow", platform="ios")  # slot freed
    out = capsys.readouterr()
    assert "tok-0000" not in out.out + out.err and "tok-overflow" not in out.out + out.err


# --------------------------------------------------------------- delivery + prefs


async def test_push_delivery_default_and_language(env):
    await env.device(locale="en")
    rep = await env.alert()
    assert (
        rep.alerts_created == 1
        and rep.pushes_sent == 1
        and env.push.sent[0]["title"].startswith("You have")
    )
    await env.prefs(language="ar")
    env.advance(days=2)
    env.mock.set_price("lst_1", "20")
    await env.svc.evaluate_all()
    assert env.push.sent[-1]["title"].startswith("لديك")  # prefs language beats device locale


async def test_channel_pref_disables_push(env):
    await env.device()
    await env.prefs(channels={"price_drop": ["in_app"]})
    rep = await env.alert()
    assert rep.alerts_created == 1 and env.push.sent == []
    assert await env.svc.store.list_deliveries() == []  # nothing even enqueued


async def test_pref_changed_after_enqueue_is_enforced_at_delivery_time(env):
    await env.device()
    env.push.script[TOKEN] = [PushResult(False, "http_503", retryable=True)]
    await env.alert()
    (d,) = await env.svc.store.list_deliveries()
    assert d.status is DeliveryStatus.PENDING
    await env.prefs(channels={"price_drop": ["in_app"]})
    env.advance(minutes=5)
    await env.svc.delivery.process_due()
    (d,) = await env.svc.store.list_deliveries()
    assert d.status is DeliveryStatus.SKIPPED and d.last_error == "prefs_disabled"
    assert env.push.sent == []


async def test_quiet_hours_defer_until_local_end(env):
    await env.device()
    env.now = datetime(2026, 10, 13, 20, 0, tzinfo=UTC)  # 23:00 Baghdad
    await env.prefs(quiet_hours={"start": "22:00", "end": "07:00"}, timezone="Asia/Baghdad")
    rep = await env.alert()
    assert rep.pushes_sent == 0 and env.push.sent == []
    (d,) = await env.svc.store.list_deliveries()
    assert d.status is DeliveryStatus.PENDING and d.attempts == 0  # deferral is not an attempt
    assert d.next_attempt_at == datetime(2026, 10, 14, 4, 0, tzinfo=UTC)  # 07:00 Baghdad
    env.now = datetime(2026, 10, 14, 3, 59, tzinfo=UTC)
    assert await env.svc.delivery.process_due() == 0
    env.now = datetime(2026, 10, 14, 4, 0, tzinfo=UTC)
    assert await env.svc.delivery.process_due() == 1 and len(env.push.sent) == 1


async def test_prefs_validation_and_roundtrip(env):
    h = {"X-User-Id": "u1"}
    default = (await env.c.get("/v1/notification-prefs", headers=h)).json()
    assert default["language"] is None and default["channels"]["price_drop"] == ["in_app", "push"]
    for bad in (
        {"channels": {"nope": ["push"]}},
        {"channels": {"price_drop": ["sms"]}},
        {"timezone": "Mars/Base"},
        {"quiet_hours": {"start": "25:99", "end": "07:00"}},
        {"language": "fr"},
        {"email": "not-an-email"},
    ):
        assert (await env.c.put("/v1/notification-prefs", headers=h, json=bad)).status_code in (
            422,
            400,
        ), bad
    saved = await env.prefs(
        language="en", email="a@example.com", quiet_hours={"start": "23:00", "end": "06:00"}
    )
    assert (await env.c.get("/v1/notification-prefs", headers=h)).json() == saved
    cleared = await env.prefs(clear_quiet_hours=True)
    assert cleared["quiet_hours"] is None and cleared["language"] == "en"
    assert (await env.c.get("/v1/notification-prefs")).status_code == 401


# --------------------------------------------------------------- retry / dead letter / invalid


async def test_retry_backoff_then_dead_letter(env):
    await env.device()
    env.push.script[TOKEN] = [PushResult(False, "http_503", retryable=True)]
    await env.alert()
    (d,) = await env.svc.store.list_deliveries()
    assert (d.attempts, d.status) == (1, DeliveryStatus.PENDING)
    assert d.next_attempt_at == T0 + timedelta(seconds=30)
    assert await env.svc.delivery.process_due() == 0 and len(env.push.attempts) == 1  # not due
    env.advance(seconds=30)
    await env.svc.delivery.process_due()
    (d,) = await env.svc.store.list_deliveries()
    assert d.attempts == 2 and d.next_attempt_at == env.now + timedelta(seconds=60)  # doubled
    env.advance(seconds=60)
    await env.svc.delivery.process_due()
    (d,) = await env.svc.store.list_deliveries()
    assert d.status is DeliveryStatus.DEAD and d.attempts == 3 and d.last_error == "http_503"
    env.advance(days=1)
    await env.svc.delivery.process_due()
    assert len(env.push.attempts) == 3 and env.push.sent == []  # dead letters are never retried


async def test_retry_succeeds_after_transient_failure(env):
    await env.device()
    env.push.script[TOKEN] = [PushResult(False, "http_503", retryable=True), PushResult(True)]
    await env.alert()
    env.advance(seconds=30)
    assert await env.svc.delivery.process_due() == 1
    (d,) = await env.svc.store.list_deliveries()
    assert d.status is DeliveryStatus.SENT and d.attempts == 2


async def test_invalid_token_deactivates_device(env):
    dev = await env.device()
    env.push.script[TOKEN] = [PushResult(False, "unregistered", invalid_token=True)]
    await env.alert()
    (d,) = await env.svc.store.list_deliveries()
    assert d.status is DeliveryStatus.INVALID_TOKEN
    listed = (await env.c.get("/v1/devices", headers={"X-User-Id": "u1"})).json()["items"]
    assert listed[0]["active"] is False
    env.advance(days=2)
    env.mock.set_price("lst_1", "10")
    await env.svc.evaluate_all()
    assert len(env.push.attempts) == 1  # no new delivery to the dead token
    again = await env.device()  # re-registering reactivates
    assert again["id"] == dev["id"] and again["active"] is True


async def test_enqueue_is_idempotent(env):
    await env.device()
    rep = await env.alert()
    alerts = rep.alerts
    assert len(env.push.sent) == 1
    assert await env.svc.delivery.enqueue_alerts("u1", alerts) == 0  # same ids -> no new row
    await env.svc.delivery.process_due()
    assert len(env.push.sent) == 1 and len(await env.svc.store.list_deliveries()) == 1


async def test_provider_crash_never_blocks_alert_creation(env):
    await env.device()

    class Boom:
        async def send(self, *a, **k):
            raise RuntimeError("provider exploded " + TOKEN)

    env.svc.delivery.push = Boom()
    rep = await env.alert()
    assert rep.alerts_created == 1
    (d,) = await env.svc.store.list_deliveries()
    assert d.status is DeliveryStatus.PENDING and TOKEN not in (d.last_error or "")


# --------------------------------------------------------------- email digest


async def test_daily_digest_idempotent_and_localised(env):
    await env.device()
    await env.alert()
    await env.prefs(
        channels={"price_drop": ["in_app", "email"]},
        digest_email="buyer@example.com",
        language="ar",
    )
    await env.verify()
    env.email.sent.clear()  # drop the verification mail
    env.now = datetime(2026, 10, 13, 4, 0, tzinfo=UTC) + timedelta(hours=9)  # 16:00 Baghdad
    assert await env.svc.send_digests() == 1
    assert await env.svc.send_digests() == 0  # same local day
    (mail,) = env.email.sent
    assert mail["to"] == "buyer@example.com" and "ملخصك" in mail["subject"]
    env.advance(days=1)
    await env.svc.send_digests()  # nothing new in the last 24h
    assert len(env.email.sent) == 1


# --------------------------------------------------------------- providers / config


def _dev(platform=Platform.ANDROID):
    return Device("dev_1", "u1", platform, Locale.EN, TOKEN, T0, T0)


async def test_fcm_request_shape():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"name": "projects/p/messages/1"})

    async def tokens() -> str:
        return "ya29.fake"

    fcm = FcmPush("proj-1", tokens, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    res = await fcm.send(_dev(), "T", "B", {"alert_id": "alt_1", "count": "2"})
    assert res.sent
    (req,) = seen
    assert str(req.url) == "https://fcm.googleapis.com/v1/projects/proj-1/messages:send"
    assert req.headers["authorization"] == "Bearer ya29.fake"
    msg = json.loads(req.content)["message"]
    assert msg["token"] == TOKEN and msg["notification"] == {"title": "T", "body": "B"}
    assert msg["data"] == {"alert_id": "alt_1", "count": "2"} and "android" in msg
    await fcm.send(_dev(Platform.IOS), "T", "B", {})
    assert "apns" in json.loads(seen[1].content)["message"]


@pytest.mark.parametrize(
    ("status", "body", "invalid", "retry"),
    [
        (
            404,
            {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}},
            True,
            False,
        ),
        (400, {"error": {"status": "INVALID_ARGUMENT"}}, True, False),
        (503, {}, False, True),
        (429, {}, False, True),
        (403, {}, False, True),
    ],
)
async def test_fcm_error_mapping_and_no_token_in_reason(status, body, invalid, retry):
    async def tokens() -> str:
        return "x"

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body))
    )
    res = await FcmPush("p", tokens, client).send(_dev(), "T", "B", {})
    assert not res.sent and res.invalid_token is invalid and res.retryable is retry
    assert TOKEN not in (res.reason or "")


async def test_fcm_transport_error_is_retryable():
    def boom(req):
        raise httpx.ConnectError("down")

    async def tokens() -> str:
        return "x"

    fcm = FcmPush("p", tokens, httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    res = await fcm.send(_dev(), "T", "B", {})
    assert res.retryable and not res.sent


def test_providers_off_by_default_and_secrets_not_in_repr():
    s = Settings(database_url="sqlite+aiosqlite:///:memory:")
    assert build_push(s) is None and build_email(s) is None
    assert isinstance(build_push(Settings(FF_NOTIFY_PUSH="mock")), MockPush)
    s2 = Settings(
        FF_NOTIFY_PUSH="fcm",
        FF_NOTIFY_FCM_PROJECT_ID="p",
        FF_NOTIFY_FCM_CREDENTIALS_JSON='{"private_key": "SUPERSECRET"}',
        FF_NOTIFY_SMTP_PASSWORD="pw-secret",
    )
    assert isinstance(build_push(s2), FcmPush)
    assert "SUPERSECRET" not in repr(s2) and "pw-secret" not in repr(s2)


async def test_service_account_token_provider_signs_and_caches():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from ff_notifications.adapters.push import ServiceAccountTokenProvider

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    creds = json.dumps({"client_email": "sa@p.iam.gserviceaccount.com", "private_key": pem})
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json={"access_token": "tok1", "expires_in": 3600})

    prov = ServiceAccountTokenProvider(
        creds, None, httpx.AsyncClient(transport=httpx.MockTransport(handler)), clock=lambda: 1000.0
    )
    assert await prov() == "tok1" and await prov() == "tok1"
    assert len(calls) == 1 and b"jwt-bearer" in calls[0].content
