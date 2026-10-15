"""QA2: demand races on a file-backed sqlite DB (two services/engines on one file = two replicas).
Publish must never double-send; approve is exclusive; cap/cooldown hold under contention."""

import asyncio
from datetime import UTC, datetime

import pytest

from ff_demand.config import Settings
from ff_demand.errors import ApiError
from ff_demand.publisher import MockPublisher
from ff_demand.service import DemandService
from ff_demand.signals import RawSignal
from ff_demand.sourcing import MockSourcingClient
from ff_demand.store import Store

AR = "أحتاج مكائن تعبئة من الصين"
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)


class SlowPublisher(MockPublisher):
    async def publish(self, draft, actor):
        await asyncio.sleep(0.05)  # widen the window between guard and send
        return await super().publish(draft, actor)


@pytest.fixture
async def svcs(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/d.db"
    cfg = Settings(database_url=url, enabled=True, daily_cap=20)
    pub = SlowPublisher()  # shared recorder: counts sends across both replicas
    out, stores = [], []
    for _ in range(2):
        st = Store(url)
        stores.append(st)
        s = DemandService(st, MockSourcingClient(), cfg, publisher=pub)
        s.clock = lambda: NOW
        out.append(s)
    await stores[0].create_all()
    yield out, pub
    for st in stores:
        await st.dispose()


async def _draft(svc, text=AR, url=None):
    return (await svc.import_signal(RawSignal(text, url, "manual")))["draft"]["id"]


def _ok(res):
    return [r for r in res if not isinstance(r, BaseException)]


def _errs(res):
    bad = [r for r in res if isinstance(r, BaseException)]
    assert all(isinstance(b, ApiError) for b in bad), bad
    return bad


async def test_concurrent_publish_never_double_sends(svcs):
    (a, b), pub = svcs
    did = await _draft(a)
    await a.approve(did, "alice", None)
    res = await asyncio.gather(
        *[(a, b)[i % 2].publish_via_adapter(did, "alice") for i in range(8)], return_exceptions=True
    )
    assert len(_ok(res)) == 1, res
    _errs(res)
    assert pub.published == [(did, "alice")]  # sent exactly once
    assert (await a.get_draft(did))["status"] == "published"


async def test_repeated_publish_after_success_does_not_resend(svcs):
    (a, b), pub = svcs
    did = await _draft(a)
    await a.approve(did, "alice", None)
    await a.publish_via_adapter(did, "alice")
    with pytest.raises(ApiError):
        await b.publish_via_adapter(did, "alice")
    assert len(pub.published) == 1


async def test_failed_send_before_post_releases_claim(svcs):
    (a, b), pub = svcs
    did = await _draft(a)
    await a.approve(did, "alice", None)
    real = pub.publish

    async def boom(d, actor):
        raise ApiError("refused")

    pub.publish = boom
    with pytest.raises(ApiError):
        await a.publish_via_adapter(did, "alice")
    pub.publish = real
    await b.publish_via_adapter(did, "alice")  # retry works: nothing was sent the first time
    assert len(pub.published) == 1


async def test_ambiguous_send_failure_keeps_claim_no_resend(svcs):
    (a, b), pub = svcs

    async def flaky(d, actor):
        raise TimeoutError("unknown whether posted")

    pub.publish = flaky
    did = await _draft(a)
    await a.approve(did, "alice", None)
    with pytest.raises(TimeoutError):
        await a.publish_via_adapter(did, "alice")
    with pytest.raises(ApiError):  # never auto re-sent
        await b.publish_via_adapter(did, "alice")
    with pytest.raises(ApiError):  # nor silently marked published/edited behind the claim
        await b.mark_published(did, "alice", None)
    with pytest.raises(ApiError):
        await b.edit(did, "alice", "نص جديد مختلف تماما هنا")


async def test_double_approve_one_wins_and_manual_publish_once(svcs):
    (a, b), _ = svcs
    did = await _draft(a)
    res = await asyncio.gather(
        *[(a, b)[i % 2].approve(did, "alice", None) for i in range(6)], return_exceptions=True
    )
    assert len(_ok(res)) == 1, res
    _errs(res)
    res = await asyncio.gather(
        *[(a, b)[i % 2].mark_published(did, "alice", "https://x.test/1") for i in range(6)],
        return_exceptions=True,
    )
    assert len(_ok(res)) == 1, res
    _errs(res)


async def test_approve_vs_reject_race_consistent(svcs):
    (a, b), _ = svcs
    did = await _draft(a)
    res = await asyncio.gather(
        a.approve(did, "alice", None), b.reject(did, "bob", "no"), return_exceptions=True
    )
    assert len(_ok(res)) >= 1
    _errs(res)
    assert (await a.get_draft(did))["status"] in ("approved", "rejected")


async def test_daily_cap_holds_under_concurrent_approvals(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/c.db"
    cfg = Settings(database_url=url, enabled=True, daily_cap=3)
    sts = [Store(url), Store(url)]
    await sts[0].create_all()
    svcs_ = []
    for st in sts:
        s = DemandService(st, MockSourcingClient(), cfg)
        s.clock = lambda: NOW
        svcs_.append(s)
    ids = [await _draft(svcs_[0], AR + f" نوع{i}", f"https://t.test/{i}") for i in range(8)]
    res = await asyncio.gather(
        *[svcs_[i % 2].approve(d, "alice", None) for i, d in enumerate(ids)], return_exceptions=True
    )
    assert len(_ok(res)) == 3, res
    _errs(res)
    for st in sts:
        await st.dispose()


async def test_duplicate_signal_import_race_one_signal_one_draft(svcs):
    (a, b), _ = svcs
    res = await asyncio.gather(
        *[
            (a, b)[i % 2].import_signal(RawSignal(AR, "https://t.test/dup", "manual"))
            for i in range(6)
        ],
        return_exceptions=True,
    )
    assert all(not isinstance(r, BaseException) for r in res), res
    assert sum(1 for r in res if r["created"]) == 1
    assert (
        len({r["draft"]["id"] for r in res if r["draft"]}) <= 1
    )  # losers may see the winner's draft late
    assert len(await a.store.list_signals()) == 1
