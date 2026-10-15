"""QA pass 2: concurrent uploads / quota / sign-delete races on a file-backed SQLite database."""

import asyncio

import pytest
from conftest import solid
from sqlalchemy import func, select

from ff_media.config import Settings
from ff_media.db import MediaFileRow, make_engine
from ff_media.errors import MediaError, NotFound
from ff_media.service import MediaService
from ff_media.storage import LocalDiskStorage


@pytest.fixture
async def svc(tmp_path):
    s = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/m.db", storage_root=str(tmp_path / "store"),
        signing_key="k" * 32, max_uploads_per_hour=5, max_files_per_user=3,
    )
    sv = MediaService(make_engine(s.database_url), s, LocalDiskStorage(str(tmp_path / "store")))
    await sv.create_tables()
    yield sv
    await sv.engine.dispose()


def _blobs(tmp_path):
    return [p for p in (tmp_path / "store").rglob("*") if p.is_file()]


async def test_identical_concurrent_uploads_store_one_row_and_no_orphan_blobs(svc, tmp_path):
    res = await asyncio.gather(*[svc.store("alice", "listing", solid(1), "private") for _ in range(8)], return_exceptions=True)
    assert not [r for r in res if isinstance(r, Exception)], res
    assert len({img.id for img, _ in res}) == 1 and sum(1 for _, created in res if created) == 1
    async with svc.sessions() as s:
        assert await s.scalar(select(func.count()).select_from(MediaFileRow)) == 1
    assert len(_blobs(tmp_path)) == 1  # losers cleaned their blobs


async def test_file_quota_not_overshot_by_concurrent_uploads(svc):
    res = await asyncio.gather(*[svc.store("alice", "listing", solid(i)) for i in range(8)], return_exceptions=True)
    assert not [r for r in res if isinstance(r, Exception) and not isinstance(r, MediaError)], res
    async with svc.sessions() as s:
        assert await s.scalar(select(func.count()).select_from(MediaFileRow)) <= 3


async def test_hourly_quota_holds_under_concurrency(svc):
    res = await asyncio.gather(*[svc.charge_hourly("alice") for _ in range(12)], return_exceptions=True)
    assert sum(1 for r in res if r is None) == 5
    assert not [r for r in res if isinstance(r, Exception) and not isinstance(r, MediaError)], res


async def test_delete_races_with_sign_and_read(svc):
    img, _ = await svc.store("alice", "verification", solid(9), "private")
    out = await asyncio.gather(
        svc.delete("alice", img.id), svc.sign_url("alice", img.id), svc.delete("alice", img.id), return_exceptions=True
    )
    assert not [o for o in out if isinstance(o, Exception) and not isinstance(o, NotFound)], out
    with pytest.raises(NotFound):
        await svc.read_admin(img.id)
