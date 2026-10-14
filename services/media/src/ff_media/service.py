from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ff_media.config import Settings
from ff_media.db import Base, MediaFileRow, UploadEventRow
from ff_media.errors import NotFound, QuotaFiles, QuotaUploads, StorageUnavailable
from ff_media.imaging import Processed, process_image
from ff_media.schemas import MediaImage
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

    async def create_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    def to_image(self, row: MediaFileRow) -> MediaImage:
        return MediaImage(
            id=row.id, url=f"{self.settings.base}/v1/media/files/{row.id}.{row.ext}", width=row.width,
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

    async def store(self, owner: str, kind: str, data: bytes) -> tuple[MediaImage, bool]:
        s_ = self.settings
        proc: Processed = await asyncio.to_thread(
            process_image, data, max_dimension=s_.max_dimension, max_pixels=s_.max_pixels, jpeg_quality=s_.jpeg_quality
        )  # fmt: skip
        async with self.sessions() as s:
            existing = await self._by_hash(s, owner, proc.sha256)
            if existing:
                return self.to_image(existing), False
            count = await s.scalar(select(func.count()).select_from(MediaFileRow).where(MediaFileRow.owner_id == owner))
            if (count or 0) >= s_.max_files_per_user:
                raise QuotaFiles(f"Stored file limit reached ({s_.max_files_per_user})", {"limit": s_.max_files_per_user})
            media_id = secrets.token_hex(16)
            keys = [make_key(media_id, proc.ext)] + [make_key(media_id, proc.ext, w) for w in proc.variants]
            try:
                await self.storage.put(keys[0], proc.data, proc.content_type)
                for w, blob in proc.variants.items():
                    await self.storage.put(make_key(media_id, proc.ext, w), blob, proc.content_type)
            except Exception as e:
                await self._cleanup(keys)
                raise StorageUnavailable("Storage is not available") from e
            row = MediaFileRow(
                id=media_id, owner_id=owner, kind=kind, content_type=proc.content_type, ext=proc.ext,
                width=proc.width, height=proc.height, size_bytes=len(proc.data), sha256=proc.sha256,
                widths=",".join(str(w) for w in proc.variants), created_at=self.clock(),
            )  # fmt: skip
            s.add(row)
            try:
                await s.commit()
            except IntegrityError:  # concurrent identical upload won the race
                await s.rollback()
                await self._cleanup(keys)
                again = await self._by_hash(s, owner, proc.sha256)
                if again is None:
                    raise
                return self.to_image(again), False
            except Exception:
                await self._cleanup(keys)
                raise
            return self.to_image(row), True

    @staticmethod
    async def _by_hash(s, owner: str, sha: str) -> MediaFileRow | None:
        return await s.scalar(select(MediaFileRow).where(MediaFileRow.owner_id == owner, MediaFileRow.sha256 == sha))

    async def _cleanup(self, keys: list[str]) -> None:
        for k in keys:
            with contextlib.suppress(Exception):  # best effort
                await self.storage.delete(k)

    async def delete(self, owner: str, media_id: str) -> None:
        async with self.sessions() as s:
            row = await s.get(MediaFileRow, media_id)
            if row is None or row.owner_id != owner:  # same answer for "missing" and "someone else's"
                raise NotFound("Image not found")
            keys = [make_key(row.id, row.ext)] + [make_key(row.id, row.ext, int(w)) for w in row.widths.split(",") if w]
            await s.delete(row)
            await s.commit()
        await self._cleanup(keys)
