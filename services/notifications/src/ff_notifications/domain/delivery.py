"""Delivery domain: preferences, quiet hours, deliveries and backoff (pure, no I/O)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ff_notifications.domain.models import Locale, RuleKind

IN_APP, PUSH, EMAIL = "in_app", "push", "email"
CHANNELS = (IN_APP, PUSH, EMAIL)
DEFAULT_CHANNELS = (IN_APP, PUSH)
DEFAULT_TIMEZONE = "Asia/Baghdad"


class DeliveryStatus(StrEnum):
    PENDING = "pending"  # waiting for (re)try; next_attempt_at says when
    SENT = "sent"
    SKIPPED = "skipped"  # prefs / no device / provider off at delivery time
    DEAD = "dead"  # retries exhausted (dead letter)
    INVALID_TOKEN = "invalid_token"  # noqa: S105 # provider said the token is gone; device deactivated


def parse_hhmm(value: str) -> time:
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid time {value!r}, expected HH:MM") from exc


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


@dataclass(frozen=True, slots=True)
class QuietHours:
    start: str  # "HH:MM" local time, may wrap midnight (22:00 -> 07:00)
    end: str

    def _window(self) -> tuple[time, time]:
        return parse_hhmm(self.start), parse_hhmm(self.end)

    def active(self, local: datetime) -> bool:
        s, e = self._window()
        t = local.time().replace(second=0, microsecond=0)
        if s == e:
            return False
        return s <= t < e if s < e else (t >= s or t < e)

    def ends_at(self, local: datetime) -> datetime:
        """Next local datetime at which the quiet window ends (assumes ``active(local)``)."""
        _, e = self._window()
        end = local.replace(hour=e.hour, minute=e.minute, second=0, microsecond=0)
        return end if end > local else end + timedelta(days=1)


@dataclass(frozen=True, slots=True)
class Prefs:
    owner_id: str
    channels: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {r.value: DEFAULT_CHANNELS for r in RuleKind}
    )
    quiet_hours: QuietHours | None = None
    timezone: str = DEFAULT_TIMEZONE
    language: Locale | None = None  # None = per-device locale
    digest_email: str | None = None  # VERIFIED address; the only one the digest is sent to
    digest_email_pending: str | None = None  # awaiting the code; never mailed a digest
    explicit: bool = False  # True once the user saved prefs

    def allows(self, rule: str, channel: str) -> bool:
        return channel in self.channels.get(rule, DEFAULT_CHANNELS)

    def in_quiet_hours(self, now: datetime) -> QuietHours | None:
        if self.quiet_hours and self.quiet_hours.active(now.astimezone(ZoneInfo(self.timezone))):
            return self.quiet_hours
        return None

    def quiet_until(self, now: datetime) -> datetime | None:
        qh = self.in_quiet_hours(now)
        if qh is None:
            return None
        return qh.ends_at(now.astimezone(ZoneInfo(self.timezone))).astimezone(now.tzinfo)


@dataclass(frozen=True, slots=True)
class Delivery:
    id: str
    owner_id: str
    channel: str  # push | email
    kind: str  # alerts | digest
    alert_ids: tuple[str, ...]
    created_at: datetime
    next_attempt_at: datetime
    device_id: str | None = None
    status: DeliveryStatus = DeliveryStatus.PENDING
    attempts: int = 0
    last_error: str | None = None
    updated_at: datetime | None = None


def delivery_id(*parts: str) -> str:
    """Deterministic id => re-enqueueing the same logical delivery is a no-op."""
    return "dlv_" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def backoff_seconds(attempts: int, base: float, cap: float) -> float:
    """Delay before the next try after ``attempts`` failures (1 -> base, doubling, capped)."""
    return min(cap, base * (2 ** max(0, attempts - 1)))
