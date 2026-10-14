"""Push providers: ``MockPush`` (tests) and ``FcmPush`` (FCM HTTP v1; UNVERIFIED against live).

Credentials come only from the environment (see ``ServiceAccountTokenProvider``). Tokens and
access tokens are never logged or put in error strings.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from ff_notifications.domain.models import Device, Platform

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"


@dataclass(frozen=True, slots=True)
class PushResult:
    sent: bool
    reason: str | None = None
    invalid_token: bool = False  # token is permanently dead -> deactivate the device
    retryable: bool = False  # transient failure -> retry with backoff


class PushProvider(Protocol):
    async def send(
        self, device: Device, title: str, body: str, data: dict[str, str]
    ) -> PushResult: ...


PushAdapter = PushProvider  # backwards-compatible name


@dataclass(slots=True)
class MockPush:
    """Records sent messages. ``script`` maps a token to a PushResult to simulate failures."""

    sent: list[dict] = field(default_factory=list)
    script: dict[str, list[PushResult]] = field(default_factory=dict)
    attempts: list[str] = field(default_factory=list)  # device ids, one per send() call

    async def send(self, device: Device, title: str, body: str, data: dict[str, str]) -> PushResult:
        self.attempts.append(device.id)
        queue = self.script.get(device.token)
        if queue:
            res = queue.pop(0) if len(queue) > 1 else queue[0]
            if not res.sent:
                return res
        self.sent.append(
            {
                "device_id": device.id,
                "owner_id": device.owner_id,
                "token": device.token,
                "title": title,
                "body": body,
                "data": data,
            }
        )
        return PushResult(True)


MockPushAdapter = MockPush  # backwards-compatible name

TokenProvider = Callable[[], Awaitable[str]]


class FcmPush:
    """FCM HTTP v1 sender. ``token_provider`` returns an OAuth2 access token (injected so tests
    and the real service-account flow are interchangeable). Off unless wired by config."""

    def __init__(
        self,
        project_id: str,
        token_provider: TokenProvider,
        client: httpx.AsyncClient | None = None,
        enabled: bool = True,
    ) -> None:
        self.project_id = project_id
        self.token_provider = token_provider
        self.client = client or httpx.AsyncClient(timeout=10.0)
        self.enabled = enabled

    @staticmethod
    def build_message(device: Device, title: str, body: str, data: dict[str, str]) -> dict:
        msg: dict = {
            "token": device.token,
            "notification": {"title": title, "body": body},
            "data": {str(k): str(v) for k, v in data.items()},
        }
        if device.platform is Platform.ANDROID:
            msg["android"] = {"priority": "HIGH", "notification": {"channel_id": "alerts"}}
        else:
            msg["apns"] = {"payload": {"aps": {"sound": "default"}}}
        return {"message": msg}

    async def send(self, device: Device, title: str, body: str, data: dict[str, str]) -> PushResult:
        if not self.enabled:
            return PushResult(False, "fcm_disabled")
        try:
            access = await self.token_provider()
            resp = await self.client.post(
                FCM_URL.format(project=self.project_id),
                json=self.build_message(device, title, body, data),
                headers={"Authorization": f"Bearer {access}"},
            )
        except (httpx.HTTPError, OSError, RuntimeError) as exc:
            return PushResult(False, f"transport:{type(exc).__name__}", retryable=True)
        if resp.status_code == 200:
            return PushResult(True)
        code = _error_code(resp)
        if resp.status_code == 404 or code == "UNREGISTERED":
            return PushResult(False, "unregistered", invalid_token=True)
        if resp.status_code == 400 and code in {"INVALID_ARGUMENT", "SENDER_ID_MISMATCH"}:
            return PushResult(False, "invalid_token", invalid_token=True)
        if resp.status_code in (401, 403, 429) or resp.status_code >= 500:
            return PushResult(False, f"http_{resp.status_code}", retryable=True)
        return PushResult(False, f"http_{resp.status_code}")


def _error_code(resp: httpx.Response) -> str | None:
    try:
        err = resp.json().get("error", {})
    except (ValueError, AttributeError):
        return None
    for d in err.get("details", []) or []:
        if isinstance(d, dict) and d.get("errorCode"):
            return str(d["errorCode"])
    return err.get("status")


FcmPushAdapter = FcmPush


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class ServiceAccountTokenProvider:
    """Google service-account OAuth (JWT bearer) flow. UNVERIFIED against the live endpoint.

    The service-account JSON comes from ``credentials_json`` (env content) or
    ``credentials_file`` (env path). Needs the optional ``cryptography`` package to sign."""

    def __init__(
        self,
        credentials_json: str | None,
        credentials_file: str | None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._json, self._file = credentials_json, credentials_file
        self.client = client or httpx.AsyncClient(timeout=10.0)
        self.clock = clock
        self._cached: tuple[str, float] | None = None

    def _creds(self) -> dict:
        if self._json:
            return json.loads(self._json)
        if self._file:
            with open(self._file, encoding="utf-8") as fh:
                return json.load(fh)
        raise RuntimeError("fcm credentials not configured")

    def _assertion(self, creds: dict) -> str:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        now = int(self.clock())
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": creds["client_email"],
            "scope": FCM_SCOPE,
            "aud": creds.get("token_uri", "https://oauth2.googleapis.com/token"),
            "iat": now,
            "exp": now + 3600,
        }
        signing = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
        key = serialization.load_pem_private_key(creds["private_key"].encode(), password=None)
        sig = key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())  # type: ignore[union-attr]
        return f"{signing}.{_b64(sig)}"

    async def __call__(self) -> str:
        if self._cached and self._cached[1] > self.clock() + 60:
            return self._cached[0]
        creds = await asyncio.to_thread(self._creds)
        assertion = await asyncio.to_thread(self._assertion, creds)
        resp = await self.client.post(
            creds.get("token_uri", "https://oauth2.googleapis.com/token"),
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        resp.raise_for_status()
        body = resp.json()
        self._cached = (body["access_token"], self.clock() + float(body.get("expires_in", 3600)))
        return self._cached[0]
