"""Delivery pipeline: enqueue deliveries for new alerts, send with retry/backoff, daily digest.

Design: alerts are committed first; deliveries are separate rows with deterministic ids
(idempotent enqueue). Preferences are re-read at send time. Nothing here logs tokens, addresses
or provider credentials; ``last_error`` only ever holds short reason codes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ff_notifications.adapters.email import EmailProvider
from ff_notifications.adapters.push import PushProvider
from ff_notifications.config import Settings
from ff_notifications.domain import messages
from ff_notifications.domain.delivery import (
    EMAIL,
    PUSH,
    Delivery,
    DeliveryStatus,
    Prefs,
    backoff_seconds,
    delivery_id,
)
from ff_notifications.domain.models import Alert, Device, Locale
from ff_notifications.persistence.store import Store

DIGEST_HOUR = 8  # local time after which the daily digest may go out


async def load_prefs(store: Store, owner_id: str) -> Prefs:
    return await store.get_prefs(owner_id) or Prefs(owner_id=owner_id)


class DeliveryPipeline:
    def __init__(
        self,
        *,
        store: Store,
        push: PushProvider | None,
        email: EmailProvider | None,
        settings: Settings,
        clock: Callable[[], datetime],
    ) -> None:
        self.store, self.push, self.email = store, push, email
        self.settings, self.clock = settings, clock
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ enqueue

    async def enqueue_alerts(self, owner_id: str, alerts: list[Alert]) -> int:
        """One push summary per active device for the alerts the owner wants pushed."""
        if self.push is None or not alerts:
            return 0
        prefs = await load_prefs(self.store, owner_id)
        wanted = sorted(a.id for a in alerts if prefs.allows(a.rule.value, PUSH))
        if not wanted:
            return 0
        now, created = self.clock(), 0
        for device in await self.store.list_devices(owner_id):
            if not device.active:
                continue
            d = Delivery(
                id=delivery_id("alerts", PUSH, device.id, *wanted),
                owner_id=owner_id,
                channel=PUSH,
                kind="alerts",
                alert_ids=tuple(wanted),
                created_at=now,
                next_attempt_at=now,
                device_id=device.id,
            )
            created += int(await self.store.insert_delivery(d))
        return created

    async def enqueue_digests(self) -> int:
        if self.email is None:
            return 0
        now, created = self.clock(), 0
        for prefs in await self.store.owners_with_email_prefs():
            local = now.astimezone(ZoneInfo(prefs.timezone))
            if local.hour < DIGEST_HOUR:
                continue
            items, _, _ = await self.store.list_alerts(
                prefs.owner_id, unread_only=False, offset=0, limit=100
            )
            ids = sorted(
                a.id
                for a in items
                if a.created_at >= now - timedelta(hours=24) and prefs.allows(a.rule.value, EMAIL)
            )
            if not ids:
                continue
            d = Delivery(
                id=delivery_id("digest", EMAIL, prefs.owner_id, local.date().isoformat()),
                owner_id=prefs.owner_id,
                channel=EMAIL,
                kind="digest",
                alert_ids=tuple(ids),
                created_at=now,
                next_attempt_at=now,
            )
            created += int(await self.store.insert_delivery(d))
        return created

    # ------------------------------------------------------------ processing

    async def process_due(self) -> int:
        """Attempt every due delivery once. Returns the number actually sent."""
        sent = 0
        async with self._lock:
            for d in await self.store.due_deliveries(self.clock()):
                try:
                    sent += int(await self._attempt(d))
                except Exception as exc:  # a bad row must not stop the queue
                    await self._fail(d, f"internal:{type(exc).__name__}", retryable=True)
        return sent

    async def _finish(self, d: Delivery, status: DeliveryStatus, reason: str | None = None) -> None:
        await self.store.save_delivery(
            replace(
                d,
                status=status,
                last_error=reason,
                attempts=d.attempts + 1,
                updated_at=self.clock(),
            )
        )

    async def _skip(self, d: Delivery, reason: str) -> bool:
        await self.store.save_delivery(
            replace(d, status=DeliveryStatus.SKIPPED, last_error=reason, updated_at=self.clock())
        )
        return False

    async def _fail(self, d: Delivery, reason: str, *, retryable: bool) -> bool:
        attempts = d.attempts + 1
        now = self.clock()
        if not retryable or attempts >= self.settings.delivery_max_attempts:
            await self.store.save_delivery(
                replace(
                    d,
                    status=DeliveryStatus.DEAD,
                    attempts=attempts,
                    last_error=reason,
                    updated_at=now,
                )
            )
            return False
        delay = backoff_seconds(
            attempts,
            self.settings.delivery_backoff_base_seconds,
            self.settings.delivery_backoff_max_seconds,
        )
        await self.store.save_delivery(
            replace(
                d,
                attempts=attempts,
                last_error=reason,
                updated_at=now,
                next_attempt_at=now + timedelta(seconds=delay),
            )
        )
        return False

    async def _alerts(self, d: Delivery, prefs: Prefs, channel: str) -> list[Alert]:
        out = []
        for aid in d.alert_ids:
            a = await self.store.get_alert(aid)
            if a is not None and prefs.allows(a.rule.value, channel):
                out.append(a)
        return out

    async def _attempt(self, d: Delivery) -> bool:
        prefs = await load_prefs(self.store, d.owner_id)
        if d.channel == PUSH:
            return await self._attempt_push(d, prefs)
        return await self._attempt_email(d, prefs)

    async def _attempt_push(self, d: Delivery, prefs: Prefs) -> bool:
        if self.push is None:
            return await self._skip(d, "push_off")
        alerts = await self._alerts(d, prefs, PUSH)
        if not alerts:
            return await self._skip(d, "prefs_disabled")
        device: Device | None = await self.store.get_device(d.device_id or "")
        if device is None or not device.active:
            return await self._skip(d, "no_active_device")
        now = self.clock()
        if (until := prefs.quiet_until(now)) is not None:  # defer, not an attempt
            await self.store.save_delivery(replace(d, next_attempt_at=until, updated_at=now))
            return False
        lang = prefs.language or device.locale
        summary = messages.push_summary(len(alerts))
        res = await self.push.send(
            device,
            summary.title_for(lang),
            summary.body_for(lang),
            {"type": "alerts", "count": str(len(alerts)), "alert_id": alerts[0].id},
        )
        if res.sent:
            await self._finish(d, DeliveryStatus.SENT)
            return True
        if res.invalid_token:
            await self.store.update_device(replace(device, active=False, updated_at=now))
            await self._finish(d, DeliveryStatus.INVALID_TOKEN, res.reason)
            return False
        return await self._fail(d, res.reason or "push_failed", retryable=res.retryable)

    async def _attempt_email(self, d: Delivery, prefs: Prefs) -> bool:
        if self.email is None:
            return await self._skip(d, "email_off")
        alerts = await self._alerts(d, prefs, EMAIL)
        if not alerts or not prefs.digest_email:  # verified address only
            return await self._skip(d, "prefs_disabled")
        subject, body = digest_text(alerts, prefs.language or Locale.AR)
        res = await self.email.send(prefs.digest_email, subject, body)
        if res.sent:
            await self._finish(d, DeliveryStatus.SENT)
            return True
        return await self._fail(d, res.reason or "email_failed", retryable=res.retryable)


def digest_text(alerts: list[Alert], lang: Locale) -> tuple[str, str]:
    n = len(alerts)
    if lang is Locale.AR:
        subject = f"ملخصك اليومي: {messages.new_alerts_count_ar(n)}"
        lines = [f"- {a.message.title_ar}" for a in alerts[:20]]
        return subject, "\n".join(lines) + "\n\nافتح التطبيق للتفاصيل."
    subject = f"Your daily digest: {n} new alert{'s' if n != 1 else ''}"
    lines = [f"- {a.message.title}" for a in alerts[:20]]
    return subject, "\n".join(lines) + "\n\nOpen the app for details."
