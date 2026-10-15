"""QA4: a human action decided on a stale pre-claim read must not overwrite a publish claim.
(replica B read the draft as approved+unclaimed, replica A then claimed and sent it)."""

import copy
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


@pytest.fixture
async def env(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/d.db"
    cfg = Settings(database_url=url, enabled=True, daily_cap=20)
    pub = MockPublisher()
    stores, svcs = [], []
    for _ in range(2):
        st = Store(url)
        stores.append(st)
        s = DemandService(st, MockSourcingClient(), cfg, publisher=pub)
        s.clock = lambda: NOW
        svcs.append(s)
    await stores[0].create_all()
    a, b = svcs
    did = (await a.import_signal(RawSignal(AR, None, "manual")))["draft"]["id"]
    await a.approve(did, "alice", None)
    stale = copy.deepcopy(await b.get_draft(did))  # approved, unclaimed
    yield a, b, did, stale, pub
    for st in stores:
        await st.dispose()


def _use_stale(svc, stale):
    async def get(_did):
        return copy.deepcopy(stale)

    svc.get_draft = get


async def test_stale_edit_after_claim_is_rejected_and_keeps_published_state(env):
    a, b, did, stale, _pub = env
    await a.publish_via_adapter(did, "alice")
    _use_stale(b, stale)
    with pytest.raises(ApiError):
        await b.edit(did, "bob", "نص مختلف تماما بعد النشر")
    del b.get_draft
    d = await b.get_draft(did)
    assert d["status"] == "published" and d["text"] == stale["text"]


async def test_stale_edit_between_claim_and_send_cannot_void_the_claim(env):
    a, b, did, stale, _pub = env
    claimed = await a.store.claim_publish(did, "alice", "2026-10-14T10:00:00Z")  # in flight
    assert claimed
    _use_stale(b, stale)
    with pytest.raises(ApiError):
        await b.edit(did, "bob", "نص مختلف تماما أثناء النشر")
    del b.get_draft
    d = await b.get_draft(did)
    assert d["status"] == "approved" and d.get("publish_claimed_by") == "alice"
    with pytest.raises(ApiError):  # still cannot be re-claimed -> never double-sent
        await b.publish_via_adapter(did, "alice")


async def test_stale_reject_or_manual_publish_cannot_override_claim(env):
    a, b, did, stale, _pub = env
    assert await a.store.claim_publish(did, "alice", "2026-10-14T10:00:00Z")
    _use_stale(b, stale)
    with pytest.raises(ApiError):
        await b.reject(did, "bob", "no")
    with pytest.raises(ApiError):
        await b.mark_published(did, "bob", "https://x.test/1")
    del b.get_draft
    d = await b.get_draft(did)
    assert d["status"] == "approved" and d.get("publish_claimed_by") == "alice"


async def test_reject_of_claimed_draft_refused_even_with_fresh_read(env):
    a, b, did, _stale, _pub = env
    assert await a.store.claim_publish(did, "alice", "2026-10-14T10:00:00Z")
    with pytest.raises(ApiError):
        await b.reject(did, "bob", "no")
