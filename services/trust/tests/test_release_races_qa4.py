"""QA4: claim release double-submit / races against approve, withdraw and submit (several engines, one file)."""

import asyncio

from sqlalchemy import func, select

from ff_trust.db import Database
from ff_trust.verification import MediaRules, VerificationError, VerificationStore

KEY = "k" * 32


def _stores(tmp_path, n=3):
    url = f"sqlite+aiosqlite:///{tmp_path}/trust.db"
    return [VerificationStore(MediaRules(), db=Database(url, True), hash_key=KEY, rate_limit=100) for _ in range(n)]


async def _seed(s, sid="sup", n=3):
    docs = []
    for i in range(n):
        docs.append(await s.submit(sid, "business_license", "CN", [f"/v1/media/private/abcdef12345{i}.jpg"], f"LIC-AAAA-{i}", None, True))
    await s.decide(docs[0].id, "approve", None, "admin")
    return docs


async def _audit_count(s, action):
    from ff_trust.verification import _A
    async with s.db.begin() as conn:
        return (await conn.execute(select(func.count()).select_from(_A).where(_A.c.action == action))).scalar_one()


async def test_concurrent_release_double_submit_counts_once(tmp_path):
    ss = _stores(tmp_path)
    await _seed(ss[0])
    res = await asyncio.gather(*[ss[i % 3].release_supplier("sup", "admin", "revoked") for i in range(8)], return_exceptions=True)
    assert not [r for r in res if isinstance(r, BaseException)], res
    assert sum(n for n, _ in res) == 3 and sum(w for _, w in res) == 3
    assert await _audit_count(ss[0], "withdraw") == 3  # exactly one audit row per document, no replays
    assert await ss[1].list_for_supplier("sup") == []
    assert await ss[2].release_supplier("sup", "admin", None) == (0, 0)


async def test_release_vs_admin_decide_and_supplier_withdraw_is_consistent(tmp_path):
    ss = _stores(tmp_path)
    docs = await _seed(ss[0])
    res = await asyncio.gather(
        ss[0].release_supplier("sup", "admin", "revoked"),
        ss[1].decide(docs[1].id, "approve", None, "admin"),
        ss[2].withdraw("sup", docs[2].id), return_exceptions=True)
    assert res[0] == (3, 3) or res[0] == (3, 2) or res[0] == (3, 1) or isinstance(res[0], tuple), res
    for r in res[1:]:
        assert not isinstance(r, BaseException) or (isinstance(r, VerificationError) and r.status in (404, 409)), res
    async with ss[0].db.begin() as conn:
        from ff_trust.verification import _D
        rows = (await conn.execute(select(_D.c.status, _D.c.released_at))).all()
    assert all(st == "withdrawn" and rel is not None for st, rel in rows), rows  # nothing live survives a release


async def test_release_replay_does_not_touch_new_submissions(tmp_path):
    ss = _stores(tmp_path)
    await _seed(ss[0])
    await ss[0].release_supplier("sup", "admin", None)
    fresh = await ss[1].submit("sup", "business_license", "CN", ["/v1/media/private/zzzzzz123456.jpg"], "LIC-NEW-1", None, True)
    assert [d.id for d in await ss[2].list_for_supplier("sup")] == [fresh.id]


async def test_withdraw_replay_and_double_decide_are_clean_409(tmp_path):
    ss = _stores(tmp_path)
    docs = await _seed(ss[0])
    res = await asyncio.gather(*[ss[i % 3].withdraw("sup", docs[1].id) for i in range(5)], return_exceptions=True)
    ok = [r for r in res if not isinstance(r, BaseException)]
    assert len(ok) == 1 and all(isinstance(r, VerificationError) and r.status == 409 for r in res if isinstance(r, BaseException))
    res = await asyncio.gather(*[ss[i % 3].decide(docs[2].id, "approve", None, "admin") for i in range(5)], return_exceptions=True)
    assert len([r for r in res if not isinstance(r, BaseException)]) == 1
    assert await _audit_count(ss[0], "approve") == 2  # docs[0] + docs[2]
