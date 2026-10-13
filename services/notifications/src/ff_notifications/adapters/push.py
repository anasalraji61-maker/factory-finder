"""Push adapters: deterministic mock + FCM stub (disabled by default; no network here)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ff_notifications.domain.models import Device


@dataclass(frozen=True, slots=True)
class PushResult:
    sent: bool
    reason: str | None = None


class PushAdapter(Protocol):
    async def send(
        self, device: Device, title: str, body: str, data: dict[str, str]
    ) -> PushResult: ...


@dataclass(slots=True)
class MockPushAdapter:
    sent: list[dict] = field(default_factory=list)

    async def send(self, device: Device, title: str, body: str, data: dict[str, str]) -> PushResult:
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


class FcmPushAdapter:
    """Stub. A real implementation would call the FCM HTTP v1 API; it is switched off unless
    ``FF_NOTIFICATIONS_FCM_ENABLED=true`` and never used in tests."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    async def send(self, device: Device, title: str, body: str, data: dict[str, str]) -> PushResult:
        if not self.enabled:
            return PushResult(False, "fcm_disabled")
        return PushResult(False, "fcm_not_implemented")
