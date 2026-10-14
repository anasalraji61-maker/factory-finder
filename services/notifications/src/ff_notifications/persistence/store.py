"""SQLite/PostgreSQL storage: JSON documents with indexed columns for the queries we run."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    cast,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ff_notifications.dburl import normalize_database_url
from ff_notifications.domain.delivery import Delivery, DeliveryStatus, Prefs
from ff_notifications.domain.models import Alert, Device, RuleKind, Watch
from ff_notifications.domain.policy import AlertHistory
from ff_notifications.domain.verification import Verification
from ff_notifications.persistence import serde

DEFAULT_LIMIT = 100  # default page size for list reads
MAX_LIMIT = 500  # hard cap on rows per query

metadata = MetaData()

watches = Table(
    "watches",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("owner_id", String(64), nullable=False, index=True),
    Column("active", Boolean, nullable=False, default=True),
    Column("identity", String(1100), nullable=False),
    Column("version", Integer, nullable=False, default=1),
    Column("doc", JSON, nullable=False),
    Index("ix_watch_owner_identity", "owner_id", "identity"),
)
alerts = Table(
    "alerts",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("owner_id", String(64), nullable=False, index=True),
    Column("watch_id", String(40), nullable=False, index=True),
    Column("rule", String(32), nullable=False),
    Column("fingerprint", String(300), nullable=False),
    Column("created_at", String(32), nullable=False),
    Column("read", Boolean, nullable=False, default=False),
    Column("doc", JSON, nullable=False),
    Index("uq_alert_event", "watch_id", "rule", "fingerprint", unique=True),
)
devices = Table(
    "devices",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("owner_id", String(64), nullable=False, index=True),
    Column("token", String(512), nullable=False, unique=True),
    Column("doc", JSON, nullable=False),
)
prefs = Table(
    "notification_prefs",
    metadata,
    Column("owner_id", String(64), primary_key=True),
    Column("doc", JSON, nullable=False),
)
email_verifications = Table(
    "email_verifications",
    metadata,
    Column("owner_id", String(64), primary_key=True),
    Column("doc", JSON, nullable=False),
)
deliveries = Table(
    "deliveries",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("owner_id", String(64), nullable=False, index=True),
    Column("status", String(16), nullable=False),
    Column("next_attempt_at", String(32), nullable=False),
    Column("doc", JSON, nullable=False),
    Index("ix_delivery_due", "status", "next_attempt_at"),
)


def normalize_url(url: str) -> str:
    return normalize_database_url(url)


def watch_identity(watch: Watch) -> str:
    return (
        f"listing:{watch.listing_id}"
        if watch.listing_id
        else f"search:{watch.search.canonical_key()}"
    )  # type: ignore[union-attr]


class Store:
    def __init__(self, url: str) -> None:
        url = normalize_url(url)
        opts = {} if url.startswith("sqlite") else {"pool_pre_ping": True}
        self.engine: AsyncEngine = create_async_engine(url, **opts)
        self._lock = asyncio.Lock()  # one writer at a time (SQLite); harmless elsewhere

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    # ------------------------------------------------------------------ watches

    async def find_watch_by_identity(self, owner_id: str, identity: str) -> Watch | None:
        async with self.engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        select(watches).where(
                            watches.c.owner_id == owner_id, watches.c.identity == identity
                        )
                    )
                )
                .mappings()
                .first()
            )
        return serde.watch_from_row(row) if row else None

    async def count_watches(self, owner_id: str) -> int:
        async with self.engine.connect() as conn:
            return int(
                (
                    await conn.execute(
                        select(func.count())
                        .select_from(watches)
                        .where(watches.c.owner_id == owner_id)
                    )
                ).scalar_one()
            )

    async def insert_watch(self, watch: Watch) -> None:
        async with self._lock, self.engine.begin() as conn:
            await conn.execute(
                insert(watches).values(
                    id=watch.id,
                    owner_id=watch.owner_id,
                    active=watch.active,
                    identity=watch_identity(watch),
                    version=watch.version,
                    doc=serde.watch_to_doc(watch),
                )
            )

    async def get_watch(self, watch_id: str) -> Watch | None:
        async with self.engine.connect() as conn:
            row = (
                (await conn.execute(select(watches).where(watches.c.id == watch_id)))
                .mappings()
                .first()
            )
        return serde.watch_from_row(row) if row else None

    async def list_watches(
        self,
        owner_id: str | None = None,
        *,
        active_only: bool = False,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> list[Watch]:
        limit = max(1, min(limit, MAX_LIMIT))
        stmt = select(watches).order_by(watches.c.id)
        if owner_id is not None:
            stmt = stmt.where(watches.c.owner_id == owner_id)
        if active_only:
            stmt = stmt.where(watches.c.active.is_(True))
        stmt = stmt.offset(max(0, offset)).limit(limit)
        async with self.engine.connect() as conn:
            return [serde.watch_from_row(r) for r in (await conn.execute(stmt)).mappings()]

    async def iter_active_watches(self, owner_id: str | None = None, batch: int = 200):
        """Yield every active watch in id-ordered batches (bounded memory per query)."""
        offset = 0
        while True:
            chunk = await self.list_watches(owner_id, active_only=True, limit=batch, offset=offset)
            for w in chunk:
                yield w
            if len(chunk) < min(batch, MAX_LIMIT):
                return
            offset += len(chunk)

    async def delete_watch(self, watch_id: str) -> None:
        async with self._lock, self.engine.begin() as conn:
            await conn.execute(delete(alerts).where(alerts.c.watch_id == watch_id))
            await conn.execute(delete(watches).where(watches.c.id == watch_id))

    async def alert_history(self, watch_id: str) -> AlertHistory:
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(alerts.c.rule, alerts.c.fingerprint, alerts.c.created_at).where(
                        alerts.c.watch_id == watch_id
                    )
                )
            ).all()
        last: dict[RuleKind, datetime] = {}
        prints = set()
        for rule, fp, created in rows:
            kind = RuleKind(rule)
            at = serde.parse_ts(created)
            if kind not in last or at > last[kind]:
                last[kind] = at
            prints.add((kind, fp))
        return AlertHistory(last_alert_at=last, fingerprints=frozenset(prints))

    async def save_evaluation(self, watch: Watch, new_alerts: list[Alert]) -> None:
        """Persist the new watch state and its alerts atomically."""
        async with self._lock, self.engine.begin() as conn:
            for alert in new_alerts:
                await conn.execute(
                    insert(alerts).values(
                        id=alert.id,
                        owner_id=alert.owner_id,
                        watch_id=alert.watch_id,
                        rule=alert.rule.value,
                        fingerprint=alert.fingerprint,
                        created_at=serde.ts(alert.created_at),
                        read=False,
                        doc=serde.alert_to_doc(alert),
                    )
                )
            await conn.execute(
                update(watches)
                .where(watches.c.id == watch.id)
                .values(doc=serde.watch_to_doc(watch), version=watch.version)
            )

    async def insert_alert_once(self, alert: Alert) -> bool:
        """Insert unless (watch_id, rule, fingerprint) exists already. True when inserted."""
        try:
            async with self._lock, self.engine.begin() as conn:
                hit = (
                    await conn.execute(
                        select(alerts.c.id).where(
                            alerts.c.watch_id == alert.watch_id,
                            alerts.c.rule == alert.rule.value,
                            alerts.c.fingerprint == alert.fingerprint,
                        )
                    )
                ).first()
                if hit:
                    return False
                await conn.execute(
                    insert(alerts).values(
                        id=alert.id,
                        owner_id=alert.owner_id,
                        watch_id=alert.watch_id,
                        rule=alert.rule.value,
                        fingerprint=alert.fingerprint,
                        created_at=serde.ts(alert.created_at),
                        read=False,
                        doc=serde.alert_to_doc(alert),
                    )
                )
                return True
        except IntegrityError:  # another replica inserted it between our check and insert
            return False

    # ------------------------------------------------------------------ alerts

    async def list_alerts(
        self, owner_id: str, *, unread_only: bool, offset: int, limit: int
    ) -> tuple[list[Alert], int, int]:
        base = [alerts.c.owner_id == owner_id]
        async with self.engine.connect() as conn:
            stmt = select(alerts).where(*base)
            if unread_only:
                stmt = stmt.where(alerts.c.read.is_(False))
            stmt = (
                stmt.order_by(alerts.c.created_at.desc(), alerts.c.id.desc())
                .offset(offset)
                .limit(limit)
            )
            rows = (await conn.execute(stmt)).mappings().all()
            count = select(func.count()).select_from(alerts).where(*base)
            unread = int((await conn.execute(count.where(alerts.c.read.is_(False)))).scalar_one())
            total = unread if unread_only else int((await conn.execute(count)).scalar_one())
        return [serde.alert_from_row(r) for r in rows], total, unread

    async def get_alert(self, alert_id: str) -> Alert | None:
        async with self.engine.connect() as conn:
            row = (
                (await conn.execute(select(alerts).where(alerts.c.id == alert_id)))
                .mappings()
                .first()
            )
        return serde.alert_from_row(row) if row else None

    async def mark_alerts_read(
        self, owner_id: str, at: datetime, alert_id: str | None = None
    ) -> int:
        """One UPDATE: flips the indexed `read` column and patches the JSON doc in SQL."""
        cond = [alerts.c.owner_id == owner_id, alerts.c.read.is_(False)]
        if alert_id:
            cond.append(alerts.c.id == alert_id)
        patch = json.dumps({"read": True, "read_at": serde.ts(at)})
        if self.engine.dialect.name == "sqlite":
            new_doc = func.json_patch(alerts.c.doc, patch)
        else:  # PostgreSQL: jsonb merge (JSON column -> jsonb -> JSON)
            new_doc = cast(cast(alerts.c.doc, JSONB).op("||")(cast(patch, JSONB)), JSON)
        async with self._lock, self.engine.begin() as conn:
            res = await conn.execute(update(alerts).where(*cond).values(read=True, doc=new_doc))
        return int(res.rowcount)

    # ------------------------------------------------------------------ devices

    async def upsert_device(self, device: Device) -> tuple[Device, bool]:
        async with self._lock, self.engine.begin() as conn:
            row = (
                (await conn.execute(select(devices).where(devices.c.token == device.token)))
                .mappings()
                .first()
            )
            if row is None:
                await conn.execute(
                    insert(devices).values(
                        id=device.id,
                        owner_id=device.owner_id,
                        token=device.token,
                        doc=serde.device_to_doc(device),
                    )
                )
                return device, True
            from dataclasses import replace

            existing = serde.device_from_row(row)
            merged = replace(
                existing,
                owner_id=device.owner_id,
                platform=device.platform,
                locale=device.locale,
                updated_at=device.updated_at,
                active=True,
            )
            await conn.execute(
                update(devices)
                .where(devices.c.id == existing.id)
                .values(owner_id=merged.owner_id, doc=serde.device_to_doc(merged))
            )
            return merged, False

    async def list_devices(self, owner_id: str) -> list[Device]:
        async with self.engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        select(devices).where(devices.c.owner_id == owner_id).order_by(devices.c.id)
                    )
                )
                .mappings()
                .all()
            )
        return [serde.device_from_row(r) for r in rows]

    async def get_device(self, device_id: str) -> Device | None:
        async with self.engine.connect() as conn:
            row = (
                (await conn.execute(select(devices).where(devices.c.id == device_id)))
                .mappings()
                .first()
            )
        return serde.device_from_row(row) if row else None

    async def delete_device(self, device_id: str) -> None:
        async with self._lock, self.engine.begin() as conn:
            await conn.execute(delete(devices).where(devices.c.id == device_id))

    async def update_device(self, device: Device) -> None:
        async with self._lock, self.engine.begin() as conn:
            await conn.execute(
                update(devices)
                .where(devices.c.id == device.id)
                .values(doc=serde.device_to_doc(device))
            )

    async def get_device_by_token(self, token: str) -> Device | None:
        async with self.engine.connect() as conn:
            row = (
                (await conn.execute(select(devices).where(devices.c.token == token)))
                .mappings()
                .first()
            )
        return serde.device_from_row(row) if row else None

    # ------------------------------------------------------------------ prefs

    async def get_prefs(self, owner_id: str) -> Prefs | None:
        async with self.engine.connect() as conn:
            row = (
                (await conn.execute(select(prefs).where(prefs.c.owner_id == owner_id)))
                .mappings()
                .first()
            )
        return serde.prefs_from_row(row) if row else None

    async def put_prefs(self, p: Prefs) -> None:
        doc = serde.prefs_to_doc(p)
        async with self._lock, self.engine.begin() as conn:
            res = await conn.execute(
                update(prefs).where(prefs.c.owner_id == p.owner_id).values(doc=doc)
            )
            if res.rowcount == 0:
                await conn.execute(insert(prefs).values(owner_id=p.owner_id, doc=doc))

    async def owners_with_email_prefs(
        self, *, after_owner: str | None = None, limit: int = DEFAULT_LIMIT
    ) -> list[Prefs]:
        """Keyset-paged by owner_id: scans at most `limit` prefs rows per call and returns the
        ones with digest_email set (use `iter_owners_with_email_prefs` to walk them all)."""
        q = select(prefs).order_by(prefs.c.owner_id).limit(max(1, min(limit, MAX_LIMIT)))
        if after_owner is not None:
            q = q.where(prefs.c.owner_id > after_owner)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(q)).mappings().all()
        return [x for x in (serde.prefs_from_row(r) for r in rows) if x.digest_email]

    async def iter_owners_with_email_prefs(self, batch: int = 200):
        after: str | None = None
        while True:
            q = select(prefs.c.owner_id).order_by(prefs.c.owner_id).limit(batch)
            if after is not None:
                q = q.where(prefs.c.owner_id > after)
            async with self.engine.connect() as conn:
                ids = [r[0] for r in (await conn.execute(q)).all()]
            if not ids:
                return
            for p in await self.owners_with_email_prefs(after_owner=after, limit=batch):
                yield p
            after = ids[-1]
            if len(ids) < batch:
                return

    async def get_verification(self, owner_id: str) -> Verification | None:
        async with self.engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        select(email_verifications).where(
                            email_verifications.c.owner_id == owner_id
                        )
                    )
                )
                .mappings()
                .first()
            )
        return serde.verification_from_row(row) if row else None

    async def put_verification(self, v: Verification) -> None:
        doc = serde.verification_to_doc(v)
        async with self._lock, self.engine.begin() as conn:
            res = await conn.execute(
                update(email_verifications)
                .where(email_verifications.c.owner_id == v.owner_id)
                .values(doc=doc)
            )
            if res.rowcount == 0:
                await conn.execute(insert(email_verifications).values(owner_id=v.owner_id, doc=doc))

    # ------------------------------------------------------------------ deliveries

    async def insert_delivery(self, d: Delivery) -> bool:
        """Insert unless a delivery with this (deterministic) id exists. True if inserted."""
        async with self._lock, self.engine.begin() as conn:
            exists = (
                await conn.execute(select(deliveries.c.id).where(deliveries.c.id == d.id))
            ).first()
            if exists:
                return False
            await conn.execute(
                insert(deliveries).values(
                    id=d.id,
                    owner_id=d.owner_id,
                    status=d.status.value,
                    next_attempt_at=serde.ts(d.next_attempt_at),
                    doc=serde.delivery_to_doc(d),
                )
            )
            return True

    async def get_delivery(self, delivery_id: str) -> Delivery | None:
        async with self.engine.connect() as conn:
            row = (
                (await conn.execute(select(deliveries).where(deliveries.c.id == delivery_id)))
                .mappings()
                .first()
            )
        return serde.delivery_from_row(row) if row else None

    async def list_deliveries(
        self, owner_id: str | None = None, *, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> list[Delivery]:
        q = (
            select(deliveries)
            .order_by(deliveries.c.id)
            .offset(max(0, offset))
            .limit(max(1, min(limit, MAX_LIMIT)))
        )
        if owner_id:
            q = q.where(deliveries.c.owner_id == owner_id)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(q)).mappings().all()
        return [serde.delivery_from_row(r) for r in rows]

    async def due_deliveries(self, now: datetime, limit: int = 100) -> list[Delivery]:
        async with self.engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        select(deliveries)
                        .where(
                            deliveries.c.status == DeliveryStatus.PENDING.value,
                            deliveries.c.next_attempt_at <= serde.ts(now),
                        )
                        .order_by(deliveries.c.next_attempt_at)
                        .limit(limit)
                    )
                )
                .mappings()
                .all()
            )
        return [serde.delivery_from_row(r) for r in rows]

    async def save_delivery(self, d: Delivery) -> None:
        async with self._lock, self.engine.begin() as conn:
            await conn.execute(
                update(deliveries)
                .where(deliveries.c.id == d.id)
                .values(
                    status=d.status.value,
                    next_attempt_at=serde.ts(d.next_attempt_at),
                    doc=serde.delivery_to_doc(d),
                )
            )


__all__ = ["Store", "watch_identity"]
