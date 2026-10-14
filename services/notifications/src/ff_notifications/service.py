"""Application service: watchlist, evaluation, alerts inbox, devices + push."""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ff_notifications.adapters.email import EmailProvider
from ff_notifications.adapters.push import PushProvider
from ff_notifications.clients.sourcing import SourcingClient, SourcingUnavailableError
from ff_notifications.config import Settings
from ff_notifications.delivery import DeliveryPipeline, load_prefs
from ff_notifications.domain.delivery import CHANNELS, Prefs, QuietHours, parse_hhmm, valid_timezone
from ff_notifications.domain.models import (
    Alert,
    Device,
    ListingObservation,
    Locale,
    Observation,
    Platform,
    RuleKind,
    SearchObservation,
    SearchQuery,
    Watch,
    WatchType,
)
from ff_notifications.domain.money import Money
from ff_notifications.domain.policy import CooldownPolicy, decide
from ff_notifications.domain.rules import RuleConfig, equivalence_query, evaluate
from ff_notifications.errors import Forbidden, Invalid, NotFound
from ff_notifications.persistence.store import Store, watch_identity


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def utc_now() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=now.microsecond // 1000 * 1000)


@dataclass
class EvaluationReport:
    evaluated: int = 0
    alerts_created: int = 0
    skipped: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    pushes_sent: int = 0
    alerts: list[Alert] = field(default_factory=list)


class NotificationService:
    def __init__(
        self,
        *,
        store: Store,
        sourcing: SourcingClient,
        push: PushProvider | None,
        email: EmailProvider | None = None,
        settings: Settings,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.store = store
        self.sourcing = sourcing
        self.push = push
        self.email = email
        self.settings = settings
        self.clock = clock
        self.cooldown = CooldownPolicy(default=timedelta(hours=settings.cooldown_hours))
        self.rule_config = RuleConfig(Decimal(settings.equivalent_min_saving_pct))
        self.delivery = DeliveryPipeline(
            store=store, push=push, email=email, settings=settings, clock=lambda: self.clock()
        )

    # ------------------------------------------------------------ watchlist

    async def add_watch(
        self,
        owner_id: str,
        *,
        listing_id: str | None,
        search: SearchQuery | None,
        target_price: Money | None,
        drop_threshold_pct: Decimal | None,
    ) -> tuple[Watch, bool]:
        if (listing_id is None) == (search is None):
            raise Invalid("Provide exactly one of listing_id or search", code="invalid_watch")
        threshold = (
            drop_threshold_pct
            if drop_threshold_pct is not None
            else Decimal(self.settings.default_drop_threshold_pct)
        )
        if not Decimal(0) < threshold <= Decimal(100):
            raise Invalid("drop_threshold_pct must be in (0, 100]", code="invalid_threshold")
        if target_price is not None and target_price.amount <= 0:
            raise Invalid("target_price must be positive", code="invalid_target")
        now = self.clock()
        watch = Watch(
            id=_id("wch"),
            owner_id=owner_id,
            type=WatchType.LISTING if listing_id else WatchType.SEARCH,
            drop_threshold_pct=threshold,
            created_at=now,
            updated_at=now,
            listing_id=listing_id,
            search=search,
            target_price=target_price,
        )
        existing = await self.store.find_watch_by_identity(owner_id, watch_identity(watch))
        if existing is not None:
            return existing, False
        if await self.store.count_watches(owner_id) >= self.settings.max_watches_per_user:
            raise Invalid("Watchlist is full", code="watchlist_full")
        await self.store.insert_watch(watch)
        return watch, True

    async def list_watches(self, owner_id: str) -> list[Watch]:
        return await self.store.list_watches(owner_id)

    async def delete_watch(self, owner_id: str, watch_id: str) -> None:
        watch = await self.store.get_watch(watch_id)
        if watch is None:
            raise NotFound("Watch not found", code="watch_not_found")
        if watch.owner_id != owner_id:
            raise Forbidden("Not your watch")
        await self.store.delete_watch(watch_id)

    # ------------------------------------------------------------ evaluation

    async def observe(self, watch: Watch) -> Observation:
        if watch.type is WatchType.LISTING:
            assert watch.listing_id
            listing = await self.sourcing.get_listing(watch.listing_id)
            equivalents = None
            if listing is not None and (eq := equivalence_query(listing)) is not None:
                with contextlib.suppress(SourcingUnavailableError):
                    equivalents = (await self.sourcing.search(eq)).items
            return ListingObservation(listing, equivalents)
        assert watch.search
        return SearchObservation(await self.sourcing.search(watch.search))

    async def evaluate_watch(self, watch: Watch, report: EvaluationReport) -> list[Alert]:
        now = self.clock()
        try:
            observation = await self.observe(watch)
        except SourcingUnavailableError as exc:
            report.errors.append({"watch_id": watch.id, "error": str(exc)})
            return []
        decision = decide(
            evaluate(watch, observation, now, self.rule_config),
            await self.store.alert_history(watch.id),
            now,
            self.cooldown,
        )
        new_alerts = [
            Alert(
                id=_id("alt"),
                owner_id=watch.owner_id,
                watch_id=watch.id,
                rule=d.rule,
                message=d.message,
                payload=d.payload,
                fingerprint=d.fingerprint,
                created_at=now,
            )
            for d in decision.to_create
        ]
        updated = replace(
            watch.with_state(decision.state), updated_at=now, version=watch.version + 1
        )
        await self.store.save_evaluation(updated, new_alerts)
        report.evaluated += 1
        report.skipped += [
            {"watch_id": watch.id, "rule": s.rule.value, "reason": s.reason}
            for s in decision.skipped
        ]
        return new_alerts

    async def evaluate_all(
        self, *, owner_id: str | None = None, watch_id: str | None = None
    ) -> EvaluationReport:
        report = EvaluationReport()
        watches = await self.store.list_watches(owner_id, active_only=True)
        if watch_id is not None:
            watches = [w for w in watches if w.id == watch_id]
        created: dict[str, list[Alert]] = {}
        for watch in watches:
            alerts = await self.evaluate_watch(watch, report)
            if alerts:
                created.setdefault(watch.owner_id, []).extend(alerts)
        for owner, alerts in created.items():
            report.alerts += alerts
            report.alerts_created += len(alerts)
            # alerts are already committed: delivery problems never undo or block them
            with contextlib.suppress(Exception):
                await self.delivery.enqueue_alerts(owner, alerts)
        with contextlib.suppress(Exception):
            report.pushes_sent = await self.delivery.process_due()
        return report

    # ------------------------------------------------------------ alerts inbox

    async def list_alerts(
        self, owner_id: str, *, unread_only: bool, page: int, page_size: int | None
    ):
        size = min(page_size or self.settings.page_size_default, self.settings.page_size_max)
        items, total, unread = await self.store.list_alerts(
            owner_id, unread_only=unread_only, offset=(page - 1) * size, limit=size
        )
        return items, total, unread, size

    async def mark_read(self, owner_id: str, alert_id: str) -> Alert:
        alert = await self.store.get_alert(alert_id)
        if alert is None:
            raise NotFound("Alert not found", code="alert_not_found")
        if alert.owner_id != owner_id:
            raise Forbidden("Not your alert")
        await self.store.mark_alerts_read(owner_id, self.clock(), alert_id)
        refreshed = await self.store.get_alert(alert_id)
        assert refreshed is not None
        return refreshed

    async def mark_all_read(self, owner_id: str) -> int:
        return await self.store.mark_alerts_read(owner_id, self.clock())

    # ------------------------------------------------------------ devices

    async def register_device(self, owner_id: str, platform: Platform, token: str, locale: Locale):
        now = self.clock()
        existing = await self.store.get_device_by_token(token)
        if existing is None or existing.owner_id != owner_id or not existing.active:
            active = [d for d in await self.store.list_devices(owner_id) if d.active]
            if len(active) >= self.settings.max_devices_per_user and (
                existing is None or existing.owner_id != owner_id
            ):
                raise Invalid(
                    f"Device limit reached ({self.settings.max_devices_per_user})",
                    code="device_limit",
                )
        return await self.store.upsert_device(
            Device(
                id=_id("dev"),
                owner_id=owner_id,
                platform=platform,
                locale=locale,
                token=token,
                created_at=now,
                updated_at=now,
            )
        )

    async def delete_device(self, owner_id: str, device_id: str) -> None:
        device = await self.store.get_device(device_id)
        if device is None:
            raise NotFound("Device not found", code="device_not_found")
        if device.owner_id != owner_id:
            raise Forbidden("Not your device")
        await self.store.delete_device(device_id)

    # ------------------------------------------------------------ preferences

    async def get_prefs(self, owner_id: str) -> Prefs:
        return await load_prefs(self.store, owner_id)

    async def put_prefs(
        self,
        owner_id: str,
        *,
        channels: dict[str, list[str]] | None,
        quiet_hours: dict[str, str] | None,
        timezone: str | None,
        language: Locale | None,
        email: str | None,
    ) -> Prefs:
        current = await self.get_prefs(owner_id)
        merged = dict(current.channels)
        for rule, chans in (channels or {}).items():
            if rule not in {r.value for r in RuleKind}:
                raise Invalid(f"Unknown alert type {rule!r}", code="invalid_prefs")
            if not set(chans) <= set(CHANNELS):
                raise Invalid("channels must be in_app, push or email", code="invalid_prefs")
            merged[rule] = tuple(dict.fromkeys(chans))
        tz = timezone or current.timezone
        if not valid_timezone(tz):
            raise Invalid("Unknown timezone", code="invalid_prefs")
        qh = current.quiet_hours
        if quiet_hours is not None:
            if not quiet_hours:
                qh = None
            else:
                try:
                    parse_hhmm(quiet_hours["start"])
                    parse_hhmm(quiet_hours["end"])
                except (ValueError, KeyError) as exc:
                    raise Invalid(
                        "quiet_hours needs start/end as HH:MM", code="invalid_prefs"
                    ) from exc
                qh = QuietHours(quiet_hours["start"], quiet_hours["end"])
        if (
            email is not None
            and email != ""
            and not ("@" in email and " " not in email and len(email) <= 254)
        ):
            raise Invalid("Invalid email address", code="invalid_prefs")
        prefs = Prefs(
            owner_id=owner_id,
            channels=merged,
            quiet_hours=qh,
            timezone=tz,
            language=language or current.language,
            email=(email or None) if email is not None else current.email,
            explicit=True,
        )
        await self.store.put_prefs(prefs)
        return prefs

    async def send_digests(self) -> int:
        await self.delivery.enqueue_digests()
        return await self.delivery.process_due()

    # ------------------------------------------------------------ scheduler

    async def run_scheduler(self) -> None:
        while True:
            await asyncio.sleep(self.settings.scheduler_interval_seconds)
            with contextlib.suppress(Exception):
                await self.evaluate_all()
            with contextlib.suppress(Exception):
                await self.send_digests()
