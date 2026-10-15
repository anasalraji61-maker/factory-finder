from __future__ import annotations

import asyncio
import contextlib
import secrets
import weakref
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ff_media import signing
from ff_media.config import Settings
from ff_media.db import Base, MediaFileRow, UploadEventRow
from ff_media.errors import NotFound, QuotaBytes, QuotaFiles, QuotaUploads, StorageUnavailable
from ff_media.imaging import Processed, process_image
from ff_media.schemas import MediaImage, SignedUrl
from ff_media.storage import StorageBackend, make_key

HOUR = timedelta(hours=1)


class MediaService:
    def __init__(
        self, engine: AsyncEngine, settings: Settings, storage: StorageBackend,
        clock: Callable[[], datetime] | None = None,
    ) -> None:  # fmt: skip
        self.engine, self.settings, self.storage = engine, settings, storage
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._owner_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._cpu = asyncio.Semaphore(max(1, settings.max_concurrent_processing))
        sk = settings.signing_key.get_secret_value() if settings.signing_key else ""
        self.signing_key: bytes = sk.encode() if sk else secrets.token_bytes(32)  # random per process when unset (dev)

    async def create_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    def to_image(self, row: MediaFileRow) -> MediaImage:
        private = row.visibility == "private"
        # private files: always the relative reference path (what trust stores); bytes only via signed URL / owner / admin
        url = f"/v1/media/private/{row.id}.{row.ext}" if private else f"{self.settings.base}/v1/media/files/{row.id}.{row.ext}"
        return MediaImage(
            id=row.id, url=url, visibility=row.visibility, width=row.width,
            height=row.height, bytes=row.size_bytes, content_type=row.content_type, sha256=row.sha256,
            kind=row.kind, widths=[int(x) for x in row.widths.split(",") if x], created_at=row.created_at,
        )  # fmt: skip

    async def charge_hourly(self, owner: str) -> None:
        now = self.clock()
        async with self.sessions() as s:
            since = now - HOUR
            await s.execute(delete(UploadEventRow).where(UploadEventRow.created_at < since - HOUR))
            rows = (await s.scalars(
                select(UploadEventRow.created_at).where(UploadEventRow.owner_id == owner, UploadEventRow.created_at >= since)
                .order_by(UploadEventRow.created_at)
            )).all()  # fmt: skip
            if len(rows) >= self.settings.max_uploads_per_hour:
                retry = max(1, int((rows[0] + HOUR - now).total_seconds()) + 1)
                await s.commit()
                raise QuotaUploads(
                    f"Upload limit reached ({self.settings.max_uploads_per_hour} per hour)",
                    {"limit": self.settings.max_uploads_per_hour}, {"Retry-After": str(retry)},
                )
            s.add(UploadEventRow(owner_id=owner, created_at=now))
            await s.commit()

    async def store(self, owner: str, kind: str, data: bytes, visibility: str = "public") -> tuple[MediaImage, bool]:
        # per-owner serialisation: the count/bytes quota checks are check-then-insert, so concurrent uploads by one
        # user must not interleave (in-process; across replicas the quota stays best-effort)
        lock = self._owner_locks.get(owner)
        if lock is None:
            lock = self._owner_locks[owner] = asyncio.Lock()
        async with lock:
            return await self._store(owner, kind, data, visibility)

    async def _store(self, owner: str, kind: str, data: bytes, visibility: str) -> tuple[MediaImage, bool]:
        s_ = self.settings
        async with self._cpu:  # bounded: a 40 MP decode can take several hundred MB
            proc: Processed = await asyncio.to_thread(
                process_image, data, max_dimension=s_.max_dimension, max_pixels=s_.max_pixels, jpeg_quality=s_.jpeg_quality
            )  # fmt: skip
        async with self.sessions() as s:
            private = visibility == "private"
            if private:
                proc.variants = {}  # no public-style resized copies of private documents
            existing = await self._by_hash(s, owner, proc.sha256, visibility)
            if existing:
                return self.to_image(existing), False
            count = await s.scalar(select(func.count()).select_from(MediaFileRow).where(MediaFileRow.owner_id == owner))
            if (count or 0) >= s_.max_files_per_user:
                raise QuotaFiles(f"Stored file limit reached ({s_.max_files_per_user})", {"limit": s_.max_files_per_user})
            used = await self.stored_bytes(owner, s)
            if used + len(proc.data) > s_.max_bytes_per_user:
                raise QuotaBytes(
                    f"Storage limit reached ({s_.max_bytes_per_user} bytes)",
                    {"limit_bytes": s_.max_bytes_per_user, "used_bytes": used},
                )
            media_id = secrets.token_hex(16)
            keys = [make_key(media_id, proc.ext, private=private)] + [make_key(media_id, proc.ext, w) for w in proc.variants]
            try:
                await self.storage.put(keys[0], proc.data, proc.content_type)
                for w, blob in proc.variants.items():
                    await self.storage.put(make_key(media_id, proc.ext, w), blob, proc.content_type)
            except Exception as e:
                await self._cleanup(keys)
                raise StorageUnavailable("Storage is not available") from e
            row = MediaFileRow(
                id=media_id, owner_id=owner, kind=kind, visibility=visibility, content_type=proc.content_type, ext=proc.ext,
                width=proc.width, height=proc.height, size_bytes=len(proc.data), sha256=proc.sha256,
                widths=",".join(str(w) for w in proc.variants), created_at=self.clock(),
            )  # fmt: skip
            s.add(row)
            try:
                await s.commit()
            except IntegrityError:  # concurrent identical upload won the race
                await s.rollback()
                await self._cleanup(keys)
                again = await self._by_hash(s, owner, proc.sha256, visibility)
                if again is None:
                    raise
                return self.to_image(again), False
            except Exception:
                await self._cleanup(keys)
                raise
            return self.to_image(row), True

    async def stored_bytes(self, owner: str, s=None) -> int:
        q = select(func.coalesce(func.sum(MediaFileRow.size_bytes), 0)).where(MediaFileRow.owner_id == owner)
        if s is not None:
            return int(await s.scalar(q) or 0)
        async with self.sessions() as s2:
            return int(await s2.scalar(q) or 0)

    @staticmethod
    async def _by_hash(s, owner: str, sha: str, visibility: str) -> MediaFileRow | None:
        return await s.scalar(
            select(MediaFileRow).where(
                MediaFileRow.owner_id == owner, MediaFileRow.sha256 == sha, MediaFileRow.visibility == visibility
            )
        )

    async def _cleanup(self, keys: list[str]) -> None:
        for k in keys:
            with contextlib.suppress(Exception):  # best effort
                await self.storage.delete(k)

    async def delete(self, owner: str, media_id: str) -> None:
        async with self.sessions() as s:
            row = await s.get(MediaFileRow, media_id)
            if row is None or row.owner_id != owner:  # same answer for "missing" and "someone else's"
                raise NotFound("Image not found")
            keys = [make_key(row.id, row.ext, private=row.visibility == "private")] + [
                make_key(row.id, row.ext, int(w)) for w in row.widths.split(",") if w
            ]
            # Explicit DELETE: a racing delete may already have removed the row; rowcount 0 means we lost the race.
            res = await s.execute(delete(MediaFileRow).where(MediaFileRow.id == media_id, MediaFileRow.owner_id == owner))
            await s.commit()
            if res.rowcount == 0:
                raise NotFound("Image not found")
        await self._cleanup(keys)

    # ------------------------------------------------------------------ account export / erasure
    async def export_owner(self, owner: str, cap: int = 1000) -> dict:
        async with self.sessions() as s:
            rows = (await s.scalars(select(MediaFileRow).where(MediaFileRow.owner_id == owner).order_by(MediaFileRow.created_at).limit(cap + 1))).all()
        return {
            "truncated": len(rows) > cap,
            "data": {"files": [
                {"id": r.id, "kind": r.kind, "visibility": r.visibility, "content_type": r.content_type,
                 "width": r.width, "height": r.height, "bytes": r.size_bytes, "sha256": r.sha256,
                 "created_at": r.created_at.isoformat()} for r in rows[:cap]
            ]},
        }  # fmt: skip

    async def erase_owner(self, owner: str) -> dict[str, int]:
        """Delete every file the user owns (rows, originals and variants) and the upload-quota events."""
        async with self.sessions() as s:
            rows = (await s.scalars(select(MediaFileRow).where(MediaFileRow.owner_id == owner))).all()
            keys: list[str] = []
            for row in rows:
                keys.append(make_key(row.id, row.ext, private=row.visibility == "private"))
                keys += [make_key(row.id, row.ext, int(w), private=row.visibility == "private") for w in row.widths.split(",") if w]
                await s.delete(row)
            await s.execute(delete(UploadEventRow).where(UploadEventRow.owner_id == owner))
            await s.commit()
        await self._cleanup(keys)
        return {"files_deleted": len(rows)}

    # ------------------------------------------------------------------ private files
    async def _private_row(self, media_id: str) -> MediaFileRow:
        async with self.sessions() as s:
            row = await s.get(MediaFileRow, media_id)
        if row is None or row.visibility != "private":
            raise NotFound("File not found")
        return row

    async def sign_url(self, owner: str, media_id: str) -> SignedUrl:
        row = await self._private_row(media_id)
        if row.owner_id != owner:  # same answer as "missing"
            raise NotFound("File not found")
        ttl = self.settings.signed_url_ttl_seconds
        now = self.clock()
        exp = int(now.timestamp()) + ttl
        sig = signing.sign(self.signing_key, row.id, owner, exp)
        url = f"{self.settings.base}/v1/media/private/{row.id}.{row.ext}?u={quote(owner, safe='')}&exp={exp}&sig={sig}"
        return SignedUrl(url=url, expires_at=datetime.fromtimestamp(exp, UTC), ttl_seconds=ttl)

    async def read_private(
        self, media_id: str, ext: str, viewer: str | None, u: str | None, exp: str | None, sig: str | None,
    ) -> tuple[MediaFileRow, bytes]:  # fmt: skip
        """Owner (X-User-Id) or a valid signed URL. Every failure is the same 404."""
        row = await self._private_row(media_id)
        if row.ext != ext:
            raise NotFound("File not found")
        if viewer is not None and viewer != row.owner_id:
            raise NotFound("File not found")  # an authenticated stranger gets nothing, even with a stolen link
        if viewer is None:
            now = int(self.clock().timestamp())
            if not (u and sig and exp and exp.isascii() and exp.isdigit() and len(exp) <= 12 and len(sig) <= 128):
                raise NotFound("File not found")
            e = int(exp)
            if e <= now or e > now + self.settings.signed_url_ttl_seconds + 5:
                raise NotFound("File not found")
            if u != row.owner_id or not signing.verify(self.signing_key, row.id, u, e, sig):
                raise NotFound("File not found")
        return await self._with_bytes(row)

    async def read_admin(self, media_id: str) -> tuple[MediaFileRow, bytes]:
        async with self.sessions() as s:
            row = await s.get(MediaFileRow, media_id)
        if row is None:
            raise NotFound("File not found")
        return await self._with_bytes(row)

    async def _with_bytes(self, row: MediaFileRow) -> tuple[MediaFileRow, bytes]:
        data = await self.storage.get(make_key(row.id, row.ext, private=row.visibility == "private"))
        if data is None:
            raise NotFound("File not found")
        return row, data

    # ------------------------------------------------------------------ orphan cleanup
    async def sweep_orphans(self, *, dry_run: bool = True) -> dict[str, int]:
        """Remove blobs that no database row references (failed/crashed uploads, rows deleted out of band).

        Needs a storage backend that can list keys (``LocalDiskStorage``); blobs younger than
        ``sweep_min_age_seconds`` are kept because their row may not be committed yet. Rows whose original blob is
        missing are only counted (``rows_missing_blob``), never deleted.
        """
        lister = getattr(self.storage, "list_keys", None)
        if lister is None:
            return {"scanned": 0, "orphans": 0, "deleted": 0, "rows_missing_blob": 0, "unsupported": 1}
        async with self.sessions() as s:
            rows = (await s.scalars(select(MediaFileRow))).all()
        wanted: set[str] = set()
        for r in rows:
            priv = r.visibility == "private"
            wanted.add(make_key(r.id, r.ext, private=priv))
            wanted.update(make_key(r.id, r.ext, int(w), private=priv) for w in r.widths.split(",") if w)
        cutoff = self.clock().timestamp() - self.settings.sweep_min_age_seconds
        present = await lister()
        orphans = [k for k, mtime in present if k not in wanted and mtime <= cutoff]
        if not dry_run:
            await self._cleanup(orphans)
        have = {k for k, _ in present}
        missing = sum(1 for r in rows if make_key(r.id, r.ext, private=r.visibility == "private") not in have)
        return {"scanned": len(present), "orphans": len(orphans), "deleted": 0 if dry_run else len(orphans),
                "rows_missing_blob": missing}  # fmt: skip
