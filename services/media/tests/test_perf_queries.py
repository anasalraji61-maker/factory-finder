"""Performance regressions: owner export is one bounded, index-ordered query (no per-file queries)."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, insert, text

from ff_media.config import Settings
from ff_media.db import MediaFileRow, make_engine
from ff_media.service import MediaService
from ff_media.storage.local import LocalDiskStorage

NOW = datetime(2026, 10, 14, tzinfo=UTC)


def _rows(n):
    return [dict(id=f"{i:032x}", owner_id=f"o{i % 3}", kind="product", visibility="public", content_type="image/webp",
                 ext="webp", width=1, height=1, size_bytes=10, sha256=f"{i:064x}", widths="",
                 created_at=NOW - timedelta(minutes=i)) for i in range(n)]


async def _svc(tmp_path, n=300):
    e = make_engine("sqlite+aiosqlite:///:memory:")
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", storage_root=str(tmp_path / "s"),
                 public_base_url="https://x.test")
    svc = MediaService(e, s, LocalDiskStorage(tmp_path / "s"))
    await svc.create_tables()
    async with e.begin() as c:
        await c.execute(insert(MediaFileRow), _rows(n))
    return e, svc


def test_export_owner_single_query_and_capped(tmp_path):
    async def go():
        e, svc = await _svc(tmp_path)
        n = [0]
        event.listen(e.sync_engine, "before_cursor_execute", lambda *a: n.__setitem__(0, n[0] + 1))
        out = await svc.export_owner("o1", cap=50)
        assert n[0] == 1 and len(out["data"]["files"]) == 50 and out["truncated"] is True
        ts = [f["created_at"] for f in out["data"]["files"]]
        assert ts == sorted(ts)

    asyncio.run(go())


def test_export_owner_uses_owner_created_index(tmp_path):
    async def go():
        e, _ = await _svc(tmp_path, 60)
        sql = "EXPLAIN QUERY PLAN SELECT * FROM media_files WHERE owner_id='o1' ORDER BY created_at LIMIT 20"
        async with e.connect() as c:
            plan = " ".join(str(r) for r in (await c.execute(text(sql))).all())
        assert "ix_media_files_owner_created" in plan and "TEMP B-TREE" not in plan

    asyncio.run(go())
