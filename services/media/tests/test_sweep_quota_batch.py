import asyncio
import logging
import os
from datetime import UTC, datetime

import pytest
from conftest import make_settings
from sqlalchemy import func, select

from ff_media.db import MediaFileRow
from ff_media.errors import QuotaFiles
from ff_media.main import create_app
from ff_media.storage import make_key


def _seed(client, n, old):
    svc = client.app.state.service

    async def go():
        async with svc.sessions() as s:
            for i in range(n):
                mid = f"{i:032x}"
                s.add(MediaFileRow(id=mid, owner_id=f"u{i % 7}", kind="listing", visibility="public", content_type="image/png",
                                   ext="png", width=1, height=1, size_bytes=1, sha256=f"{i:064x}", widths="",
                                   created_at=datetime(2026, 10, 1, tzinfo=UTC)))
                if i % 2 == 0:  # half have blobs
                    p = client.root / mid[:2] / make_key(mid, "png")
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b"x")
                    os.utime(p, (old, old))
            await s.commit()

    asyncio.run(go())


def test_sweep_2000_rows_batched_and_resumable(make_client, clock):
    c = make_client(sweep_batch=100, sweep_max_seconds=0)  # zero budget -> one batch per call
    old = clock.now.timestamp() - 7200
    _seed(c, 2000, old)
    orphan = c.root / "ff" / ("ff" * 16 + ".png")
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"x")
    os.utime(orphan, (old, old))
    svc = c.app.state.service
    after, calls, tot = None, 0, {"scanned": 0, "orphans": 0, "deleted": 0, "rows_missing_blob": 0}
    while True:
        r = asyncio.run(svc.sweep_orphans(dry_run=False, after=after))
        calls += 1
        for k in tot:
            tot[k] += r[k]
        after = r["next_after"]
        if r["complete"]:
            break
        assert calls < 200, (r, after)
    assert calls > 10  # really paginated
    assert tot["scanned"] == 1001 and tot["orphans"] == 1 and tot["deleted"] == 1
    assert tot["rows_missing_blob"] == 1000 and not orphan.exists()


def test_sweep_single_call_completes_with_default_budget(make_client, clock):
    c = make_client(sweep_batch=500)
    _seed(c, 2000, clock.now.timestamp() - 7200)
    r = asyncio.run(c.app.state.service.sweep_orphans(dry_run=True))
    assert r["complete"] is True and r["scanned"] == 1000 and r["orphans"] == 0 and r["rows_missing_blob"] == 1000


def test_sweep_batch_default_is_500(tmp_path):
    assert make_settings(tmp_path).sweep_batch == 500


def test_quota_recheck_in_insert_transaction(make_client):
    c = make_client(max_files_per_user=1)
    svc = c.app.state.service

    async def go():
        async with svc.sessions() as s:
            s.add(MediaFileRow(id="a" * 32, owner_id="zed", kind="listing", visibility="public", content_type="image/png",
                               ext="png", width=1, height=1, size_bytes=1, sha256="a" * 64, widths="", created_at=svc.clock()))
            await s.commit()
        async with svc.sessions() as s:
            with pytest.raises(QuotaFiles):
                await svc._recheck_quota(s, "zed", 1)
            assert await s.scalar(select(func.count()).select_from(MediaFileRow)) == 1

    asyncio.run(go())


def test_signing_key_warning_when_unset(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="ff_media"):
        create_app(make_settings(tmp_path))
    assert sum("SIGNING_KEY" in r.message for r in caplog.records) == 1
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="ff_media"):
        create_app(make_settings(tmp_path, signing_key="k" * 32))
    assert not caplog.records
