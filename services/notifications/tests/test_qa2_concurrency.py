# ruff: noqa: E501
"""QA pass 2: concurrent adds / ingests, scheduler isolation, UTC timestamps, retention (file-backed SQLite)."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta

from ff_notifications.domain.models import Locale, Platform

from .test_alert_pipeline import T0, make, watch


def ev(key="k1", owner="u1", sid="shp_1"):
    return {"dedupe_key": key, "shipment_id": sid, "owner_id": owner, "kind": "status_changed",
            "payload": {"shipment_id": sid, "owner_id": owner, "reference": "MSKU0000000",
                        "reference_type": "container", "kind": "status_changed", "status": "in_transit",
                        "previous_status": "booked", "delayed": False, "eta": None, "delay_hours": None,
                        "event_id": "e1", "occurred_at": "2026-10-01T10:00:00Z", "label": None}}


async def test_concurrent_duplicate_watch_adds_create_one(tmp_path):
    _, svc, _, _, ctx = await make(tmp_path)
    res = await asyncio.gather(*(watch(svc) for _ in range(8)))
    assert len({w.id for w in res}) == 1 and await svc.count_watches("u1") == 1
    await ctx.__aexit__(None, None, None)


async def test_concurrent_watch_adds_respect_cap(tmp_path):
    _, svc, _, _, ctx = await make(tmp_path, max_watches_per_user=2)
    mock_ids = [f"lst_{i}" for i in range(6)]
    res = await asyncio.gather(*(watch(svc, lid=i) for i in mock_ids), return_exceptions=True)
    assert await svc.count_watches("u1") == 2 and sum(isinstance(r, Exception) for r in res) == 4
    await ctx.__aexit__(None, None, None)


async def test_concurrent_tracking_ingest_creates_one_alert_and_one_push(tmp_path):
    _, svc, _, push, ctx = await make(tmp_path)
    await svc.register_device("u1", Platform.ANDROID, "tok-aaaaaaaa1", Locale.EN)
    out = await asyncio.gather(*(svc.ingest_tracking_events([ev()]) for _ in range(6)))
    assert sum(o["created"] for o in out) == 1 and sum(o["duplicates"] for o in out) == 5
    _, total, _, _ = await svc.list_alerts("u1", unread_only=False, page=1, page_size=50)
    assert total == 1
    assert len(push.sent) <= 1
    await ctx.__aexit__(None, None, None)


async def test_alert_timestamps_are_tz_aware_utc_and_retention_prunes(tmp_path):
    _, svc, mock, _, ctx = await make(tmp_path)
    await watch(svc)
    await svc.evaluate_all()
    mock.set_price("lst_1", "50")
    await svc.evaluate_all()
    alerts, total, _, _ = await svc.list_alerts("u1", unread_only=False, page=1, page_size=10)
    assert total == 1 and alerts[0].created_at.tzinfo is not None
    assert alerts[0].created_at.utcoffset() == timedelta(0)
    svc.clock = lambda: T0 + timedelta(days=svc.settings.alert_retention_days + 1)
    assert (await svc.prune())["alerts"] == 1
    await ctx.__aexit__(None, None, None)


async def test_scheduler_step_failure_does_not_stop_others_and_never_spins(tmp_path, monkeypatch):
    _, svc, _, _, ctx = await make(tmp_path)
    calls = {"eval": 0, "dig": 0, "prune": 0}
    sleeps = []

    async def bad_eval():
        calls["eval"] += 1
        raise RuntimeError("x")

    async def dig():
        calls["dig"] += 1

    async def prune():
        calls["prune"] += 1

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) > 2:
            raise asyncio.CancelledError

    svc.evaluate_all, svc.send_digests, svc.prune = bad_eval, dig, prune
    monkeypatch.setattr("ff_notifications.service.asyncio.sleep", fake_sleep)
    with contextlib.suppress(asyncio.CancelledError):
        await svc.run_scheduler()
    assert calls == {"eval": 2, "dig": 2, "prune": 2}
    await ctx.__aexit__(None, None, None)
