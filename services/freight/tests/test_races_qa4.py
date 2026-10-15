"""QA4: repeated races on state transitions; assert the cross-table invariants after every round."""

import asyncio

import pytest
from conftest import ADM, APP, QUOTE, uh
from test_concurrency import Boot, codes

ROUNDS = 8


async def _quote_state(b, qid):
    return (await b.c.get(f"/v1/freight/quotes/{qid}", headers=uh("buyer1"))).json()


@pytest.mark.parametrize("racer", ["withdraw", "revise"])
async def test_accept_vs_quote_mutation_never_accepts_a_mutated_quote(tmp_path, racer):
    async with Boot(tmp_path) as b:
        await b.forwarder("fa")
        for _ in range(ROUNDS):
            req = await b.request()
            q = await b.quote(req["id"], "fa")
            other = (b.c.post(f"/v1/freight/quotes/{q['id']}/withdraw", headers=uh("fa")) if racer == "withdraw"
                     else b.c.put(f"/v1/freight/quotes/{q['id']}", headers=uh("fa"), json={**QUOTE, "amount": "9999.00"}))
            rs = await asyncio.gather(b.accept(q["id"], json={"revision": 1}), other)
            assert all(r.status_code < 500 for r in rs), [r.text for r in rs]
            r, qs = await b.req(req["id"]), await _quote_state(b, q["id"])
            assert (r["awarded_quote_id"] == q["id"]) == (qs["status"] == "accepted"), (r, qs)
            if qs["status"] == "accepted":
                assert qs["revision"] == 1 and rs[0].status_code == 200
                assert rs[1].status_code == 409 or racer == "withdraw" and rs[1].json()["status"] != "withdrawn"
            await b.c.post(f"/v1/freight/requests/{req['id']}/close", headers=uh("buyer1"))


async def test_approve_vs_reject_rounds_and_double_reviewers(tmp_path):
    async with Boot(tmp_path) as b:
        for i in range(ROUNDS):
            u = f"fx{i}"
            aid = (await b.c.post("/v1/freight/applications", headers=uh(u), json=APP)).json()["id"]
            calls = [b.c.post(f"/v1/admin/freight/applications/{aid}/approve", headers=ADM) for _ in range(3)]
            calls += [b.c.post(f"/v1/admin/freight/applications/{aid}/reject", headers=ADM, json={"reason": "documents missing"})
                      for _ in range(3)]
            rs = await asyncio.gather(*calls)
            assert all(r.status_code < 500 for r in rs), [r.text for r in rs]
            mine = (await b.c.get("/v1/freight/applications/mine", headers=uh(u))).json()["items"][0]
            approvals = [r for r in rs[:3] if r.status_code == 200]
            if mine["status"] == "approved":
                assert len(approvals) >= 1 and len({r.json()["forwarder_id"] for r in approvals}) == 1
                assert all(r.status_code == 409 for r in rs[3:])
            else:
                assert mine["status"] == "rejected" and not approvals
                assert all(r.status_code in (200, 409) for r in rs[3:])
        fwd = (await b.c.get("/v1/admin/freight/forwarders", headers=ADM)).json()["items"]
        approved = [x for x in fwd]
        assert len({x["user_id"] if "user_id" in x else x["id"] for x in approved}) == len(approved)


async def test_close_replay_and_award_complete_counted_once(tmp_path):
    async with Boot(tmp_path) as b:
        fid = await b.forwarder("fa")
        req = await b.request()
        q = await b.quote(req["id"], "fa")
        assert (await b.accept(q["id"])).status_code == 200
        rs = await asyncio.gather(*[b.c.post(f"/v1/freight/requests/{req['id']}/close", headers=uh("buyer1"))
                                    for _ in range(6)])
        assert codes(rs) == {200: 6}, [r.text for r in rs]
        f = (await b.c.get(f"/v1/freight/forwarders/{fid}", headers=uh("buyer1"))).json()
        assert f["completed_jobs"] == 1

