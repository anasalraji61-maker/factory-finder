"""Application service: watchlist, evaluation, alerts inbox, devices + push."""

from __future__ import annotations

import asyncio
import contextlib
import re
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
from ff_notifications.domain import tracking
from ff_notifications.domain import verification as ver
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
from ff_notifications.errors import Conflict, Forbidden, Invalid, NotFound, TooManyRequests
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


_EMAIL_RE = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
)


def verification_text(code: str) -> tuple[str, str]:
    """Bilingual, link-free verification mail."""
    subject = "رمز التحقق / Verification code"
    body = (
        f"رمز التحقق الخاص بك: {code}\n"
        "صالح لمدة 15 دقيقة. لا تشاركه مع أحد. إن لم تطلبه فتجاهل هذه الرسالة.\n\n"
        f"Your verification code: {code}\n"
        "Valid for 15 minutes. Do not share it. If you did not request it, ignore this message."
    )
    return subject, body


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
        self._vlock = asyncio.Lock()
        self._watch_lock = asyncio.Lock()  # serialises check-then-insert in add_watch
        self._eval_lock = asyncio.Lock()  # one evaluation run at a time (API vs scheduler)
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
        async with self._watch_lock:
            existing = await self.store.find_watch_by_identity(owner_id, watch_identity(watch))
            if existing is not None:
                return existing, False
            if await self.store.count_watches(owner_id) >= self.settings.max_watches_per_user:
                raise Invalid("Watchlist is full", code="watchlist_full")
            await self.store.insert_watch(watch)
        return watch, True

    async def list_watches(
        self, owner_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[Watch]:
        return await self.store.list_watches(owner_id, limit=limit, offset=offset)

    async def count_watches(self, owner_id: str) -> int:
        return await self.store.count_watches(owner_id)

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
                    eq_page = await self.sourcing.search(eq)
                    # a partial page may miss the cheaper offer: skip the rule this run
                    equivalents = None if eq_page.degraded else eq_page.items
            return ListingObservation(listing, equivalents)
        assert watch.search
        page = await self.sourcing.search(watch.search)
        if page.degraded:
            # partial / mock-substituted results: absence or prices are not trustworthy, so no
            # state change and no alert (a vanished result must not look delisted or re-appear
            # as "back in stock", a substituted price must not look like a drop)
            raise SourcingUnavailableError("degraded search results (partial_results)")
        return SearchObservation(page)

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
        await self.store.save_evaluation(
            updated, new_alerts, keep=self.settings.max_alerts_per_user
        )
        report.evaluated += 1
        report.skipped += [
            {"watch_id": watch.id, "rule": s.rule.value, "reason": s.reason}
            for s in decision.skipped
        ]
        return new_alerts

    async def evaluate_all(
        self, *, owner_id: str | None = None, watch_id: str | None = None
    ) -> EvaluationReport:
        async with self._eval_lock:
            return await self._evaluate_all(owner_id=owner_id, watch_id=watch_id)

    async def _evaluate_all(
        self, *, owner_id: str | None = None, watch_id: str | None = None
    ) -> EvaluationReport:
        report = EvaluationReport()
        if watch_id is not None:
            w = await self.store.get_watch(watch_id)
            watches = [w] if w and w.active and (owner_id is None or w.owner_id == owner_id) else []
        else:
            watches = [w async for w in self.store.iter_active_watches(owner_id)]
        created: dict[str, list[Alert]] = {}
        for watch in watches:
            try:
                alerts = await self.evaluate_watch(watch, report)
            except Exception as exc:  # one broken watch never aborts the run or loses deliveries
                report.errors.append({"watch_id": watch.id, "error": type(exc).__name__})
                continue
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

    # ------------------------------------------------------------ tracking events

    async def ingest_tracking_events(self, raw_events: list[dict]) -> dict:
        """Turn tracking change events into inbox alerts (+ push per prefs); idempotent.

        Per event result: created | duplicate | invalid. The inbox is always written
        (``in_app`` never suppresses); push honors the user's channel prefs
        and quiet hours via the delivery pipeline.
        """
        results: list[dict] = []
        created: dict[str, list[Alert]] = {}
        for i, raw in enumerate(raw_events):
            key = raw.get("dedupe_key") if isinstance(raw, dict) else None
            try:
                ev = tracking.parse_event(raw)
            except tracking.InvalidEvent as exc:
                results.append(
                    {
                        "index": i,
                        "dedupe_key": key if isinstance(key, str) else None,
                        "status": "invalid",
                        "error": str(exc),
                    }
                )
                continue
            message, payload = tracking.build(ev)
            alert = Alert(
                id=_id("alt"),
                owner_id=ev.owner_id,
                watch_id=ev.watch_id,
                rule=ev.rule,
                message=message,
                payload=payload,
                fingerprint=ev.dedupe_key,
                created_at=self.clock(),
            )
            if await self.store.insert_alert_once(alert, keep=self.settings.max_alerts_per_user):
                created.setdefault(ev.owner_id, []).append(alert)
                results.append(
                    {
                        "index": i,
                        "dedupe_key": ev.dedupe_key,
                        "status": "created",
                        "alert_id": alert.id,
                    }
                )
            else:
                results.append({"index": i, "dedupe_key": ev.dedupe_key, "status": "duplicate"})
        for owner, alerts in created.items():
            with contextlib.suppress(
                Exception
            ):  # alerts are committed: delivery problems never undo them
                await self.delivery.enqueue_alerts(owner, alerts)
        pushes = 0
        if created:
            with contextlib.suppress(Exception):
                pushes = await self.delivery.process_due()
        count = lambda s: sum(1 for r in results if r["status"] == s)  # noqa: E731
        return {
            "received": len(raw_events),
            "created": count("created"),
            "duplicates": count("duplicate"),
            "invalid": count("invalid"),
            "pushes_sent": pushes,
            "results": results,
        }

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
        digest_email: str | None = None,
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
        email = digest_email
        if email and not (len(email) <= 254 and _EMAIL_RE.fullmatch(email)):
            raise Invalid("Invalid email address", code="invalid_prefs")
        async with self._vlock:
            verified, pending = await self._apply_digest_email(owner_id, current, email)
            prefs = Prefs(
                owner_id=owner_id,
                channels=merged,
                quiet_hours=qh,
                timezone=tz,
                language=language or current.language,
                digest_email=verified,
                digest_email_pending=pending,
                explicit=True,
            )
            await self.store.put_prefs(prefs)
        return prefs

    # ------------------------------------------------------------ digest e-mail verification

    async def _issue_code(self, owner_id: str, email: str, v: ver.Verification) -> None:
        """Generate + store a fresh code for ``email`` and mail it (caller holds ``_vlock``)."""
        now = self.clock()
        window = now - timedelta(seconds=ver.SEND_WINDOW_SECONDS)
        sends = tuple(t for t in v.sends if t > window)
        if len(sends) >= ver.MAX_SENDS_PER_HOUR:
            raise TooManyRequests(
                "Too many verification codes requested; try again later", code="send_limit"
            )
        if self.email is None:  # provider off: nothing can be sent, keep pending without a code
            await self.store.put_verification(ver.Verification(owner_id, email, sends=sends))
            return
        code, salt = ver.new_code(), ver.new_salt()
        locked = v.locked_until if v.locked_until and v.locked_until > now else None
        await self.store.put_verification(
            ver.Verification(
                owner_id=owner_id,
                email=email,
                salt=salt,
                code_hash=ver.hash_code(salt, owner_id, email, code),
                expires_at=now + timedelta(seconds=ver.CODE_TTL_SECONDS),
                attempts=0,
                locked_until=locked,
                sends=(*sends, now),
            )
        )
        subject, body = verification_text(code)
        await self.email.send(email, subject, body)  # failure => user can resend (counted)

    async def _apply_digest_email(
        self, owner_id: str, current: Prefs, email: str | None
    ) -> tuple[str | None, str | None]:
        """Returns (verified, pending) after applying a requested digest address."""
        if email is None:
            return current.digest_email, current.digest_email_pending
        v = await self.store.get_verification(owner_id) or ver.Verification(owner_id)
        if email == "":
            await self.store.put_verification(
                ver.Verification(owner_id, sends=v.sends, locked_until=v.locked_until)
            )
            return None, None
        same = lambda a: a is not None and a.casefold() == email.casefold()  # noqa: E731
        if same(current.digest_email):
            return current.digest_email, None
        if same(current.digest_email_pending):
            return None, current.digest_email_pending
        await self._issue_code(owner_id, email, v)  # raises before anything changes
        return None, email  # changing the address resets verification

    async def verify_digest_email(self, owner_id: str, code: str) -> Prefs:
        async with self._vlock:
            now = self.clock()
            prefs = await self.get_prefs(owner_id)
            v = await self.store.get_verification(owner_id)
            if (
                v is None
                or not prefs.digest_email_pending
                or v.email is None
                or v.email.casefold() != prefs.digest_email_pending.casefold()
            ):
                raise Conflict("No e-mail address is waiting for verification", code="no_pending")
            if v.locked_until and v.locked_until > now:
                raise TooManyRequests("Too many wrong codes; try again later", code="locked")
            if v.locked_until:  # lock elapsed: fresh attempts
                v = replace(v, locked_until=None, attempts=0)
            attempts = v.attempts + 1
            ok = ver.code_matches(v, code)
            expired = v.expires_at is None or now >= v.expires_at
            if not ok or expired:
                lock = (
                    now + timedelta(seconds=ver.LOCK_SECONDS)
                    if attempts >= ver.MAX_ATTEMPTS
                    else None
                )
                await self.store.put_verification(replace(v, attempts=attempts, locked_until=lock))
                if lock:
                    raise TooManyRequests("Too many wrong codes; try again later", code="locked")
                if ok and expired:
                    raise Invalid("Code expired; request a new one", code="code_expired")
                raise Invalid("Invalid code", code="invalid_code")
            await self.store.put_verification(
                ver.Verification(owner_id, sends=v.sends)  # burn the code
            )
            done = replace(
                prefs, digest_email=prefs.digest_email_pending, digest_email_pending=None
            )
            await self.store.put_prefs(done)
            return done

    async def resend_digest_code(self, owner_id: str) -> Prefs:
        async with self._vlock:
            prefs = await self.get_prefs(owner_id)
            if not prefs.digest_email_pending:
                raise Conflict("No e-mail address is waiting for verification", code="no_pending")
            if self.email is None:
                raise Conflict("E-mail delivery is not enabled", code="email_disabled")
            v = await self.store.get_verification(owner_id) or ver.Verification(owner_id)
            await self._issue_code(owner_id, prefs.digest_email_pending, v)
            return prefs

    async def send_digests(self) -> int:
        await self.delivery.enqueue_digests()
        return await self.delivery.process_due()

    # ------------------------------------------------------------ retention

    async def prune(self) -> dict[str, int]:
        now = self.clock()
        cut = lambda days: (now - timedelta(days=days)).isoformat(timespec="milliseconds").replace(  # noqa: E731
            "+00:00", "Z"
        )
        return await self.store.prune(
            alerts_before=cut(self.settings.alert_retention_days),
            deliveries_before=cut(self.settings.delivery_retention_days),
        )

    # ------------------------------------------------------------ scheduler

    async def run_scheduler(self) -> None:
        while True:
            await asyncio.sleep(self.settings.scheduler_interval_seconds)  # config enforces >= 1s
            with contextlib.suppress(Exception):
                await self.evaluate_all()
            with contextlib.suppress(Exception):
                await self.send_digests()
            with contextlib.suppress(Exception):
                await self.prune()
