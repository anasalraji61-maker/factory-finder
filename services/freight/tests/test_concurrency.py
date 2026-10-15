"""QA2: duplicate / racing requests (asyncio.gather) against a file-backed DB (one connection per request)."""

import asyncio
from collections import Counter

import httpx
from conftest import ADM, APP, NO_LIMITS, QUOTE, REQ, Clock, uh

from ff_freight.config import Settings
from ff_freight.main import create_app


class Boot:
    def __init__(self, tmp_path, **kw):
        self.tmp, self.kw, self.clock = tmp_path, kw, Clock()

    async def __aenter__(self):
        s = Settings(database_url=f"sqlite+aiosqlite:///{self.tmp / 'f.db'}", **{**NO_LIMITS, **self.kw})
        self.app = create_app(s, clock=self.clock)
        self.cm = self.app.router.lifespan_context(self.app)
        await self.cm.__aenter__()
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t")
        return self

    async def __aexit__(self, *a):
        await self.c.aclose()
        await self.cm.__aexit__(*a)

    async def forwarder(self, user):
        r = await self.c.post("/v1/freight/applications", headers=uh(user), json={**APP, "company_name": f"Gulf Star {user}"})
        assert r.status_code == 201, r.text
        a = await self.c.post(f"/v1/admin/freight/applications/{r.json()['id']}/approve", headers=ADM)
        assert a.status_code == 200, a.text
        return a.json()["forwarder_id"]

    async def request(self, user="buyer1"):
        r = await self.c.post("/v1/freight/requests", headers=uh(user), json=REQ)
        assert r.status_code == 201, r.text
        return r.json()

    async def quote(self, rid, user, **over):
        r = await self.c.post(f"/v1/freight/requests/{rid}/quotes", headers=uh(user), json={**QUOTE, **over})
        assert r.status_code == 201, r.text
        return r.json()

    async def accept(self, qid, user="buyer1", **kw):
        return await self.c.post(f"/v1/freight/quotes/{qid}/accept", headers=uh(user), **kw)

    async def req(self, rid, user="buyer1"):
        return (await self.c.get(f"/v1/freight/requests/{rid}", headers=uh(user))).json()


def codes(rs):
    return Counter(r.status_code for r in rs)


async def test_many_concurrent_accepts_of_same_quote_all_succeed_one_award(tmp_path):
    async with Boot(tmp_path) as b:
        await b.forwarder("fa")
        req = await b.request()
        qa = await b.quote(req["id"], "fa")
        rs = await asyncio.gather(*[b.accept(qa["id"]) for _ in range(8)])
        assert codes(rs) == {200: 8}, [r.text for r in rs]
        assert len({r.json()["request"]["awarded_at"] for r in rs}) == 1
        assert (await b.req(req["id"]))["awarded_quote_id"] == qa["id"]


async def test_concurrent_accepts_of_different_quotes_have_exactly_one_winner(tmp_path):
    async with Boot(tmp_path) as b:
        users = ["fa", "fb", "fc", "fd"]
        for u in users:
            await b.forwarder(u)
        req = await b.request()
        qs = [await b.quote(req["id"], u) for u in users]
        rs = await asyncio.gather(*[b.accept(q["id"]) for q in qs])
        assert codes(rs)[200] == 1, [(r.status_code, r.text) for r in rs]
        assert all(r.status_code == 409 for r in rs if r.status_code != 200)
        win = next(r for r in rs if r.status_code == 200).json()["quote"]["id"]
        final = await b.req(req["id"])
        assert final["awarded_quote_id"] == win and final["quote_count"] == 1
        st = Counter([(await b.c.get(f"/v1/freight/quotes/{q['id']}", headers=uh("buyer1"))).json()["status"]
                      for q in qs])
        assert st == {"accepted": 1, "rejected": 3}


async def test_accept_vs_close_vs_withdraw_never_leave_inconsistent_state(tmp_path):
    async with Boot(tmp_path) as b:
        await b.forwarder("fa")
        req = await b.request()
        qa = await b.quote(req["id"], "fa")
        accept = b.accept(qa["id"])
        close = b.c.post(f"/v1/freight/requests/{req['id']}/close", headers=uh("buyer1"))
        wd = b.c.post(f"/v1/freight/quotes/{qa['id']}/withdraw", headers=uh("fa"))
        rs = await asyncio.gather(accept, close, wd)
        assert all(r.status_code < 500 for r in rs), [r.text for r in rs]
        r = await b.req(req["id"])
        q = (await b.c.get(f"/v1/freight/quotes/{qa['id']}", headers=uh("buyer1"))).json()
        if r["awarded_quote_id"]:
            assert q["status"] == "accepted" and r["status"] in ("awarded", "closed")
        else:
            assert q["status"] != "accepted" and r["status"] != "awarded"


async def test_accept_vs_revise_cas_on_revision(tmp_path):
    async with Boot(tmp_path) as b:
        await b.forwarder("fa")
        req = await b.request()
        qa = await b.quote(req["id"], "fa")
        rv = b.c.put(f"/v1/freight/quotes/{qa['id']}", headers=uh("fa"), json={**QUOTE, "amount": "9999.00"})
        rs = await asyncio.gather(
            b.c.post(f"/v1/freight/quotes/{qa['id']}/accept", headers=uh("buyer1"), json={"revision": 1}), rv)
        assert all(r.status_code < 500 for r in rs), [r.text for r in rs]
        q = (await b.c.get(f"/v1/freight/quotes/{qa['id']}", headers=uh("buyer1"))).json()
        if q["status"] == "accepted":  # the buyer must have accepted exactly the revision they viewed
            assert q["revision"] == 1 and str(q["amount"]).startswith("2450")


async def test_concurrent_duplicate_quote_submits_one_quote_and_correct_count(tmp_path):
    async with Boot(tmp_path) as b:
        await b.forwarder("fa")
        req = await b.request()
        rs = await asyncio.gather(*[b.c.post(f"/v1/freight/requests/{req['id']}/quotes", headers=uh("fa"),
                                             json=QUOTE) for _ in range(6)])
        assert codes(rs)[201] == 1 and codes(rs)[409] == 5, [(r.status_code, r.text) for r in rs]
        assert (await b.req(req["id"]))["quote_count"] == 1


async def test_duplicate_applications_and_approvals_create_one_forwarder(tmp_path):
    async with Boot(tmp_path) as b:
        rs = await asyncio.gather(*[b.c.post("/v1/freight/applications", headers=uh("fx"), json=APP)
                                    for _ in range(5)])
        assert codes(rs)[201] == 1 and codes(rs)[409] == 4, [(r.status_code, r.text) for r in rs]
        aid = next(r for r in rs if r.status_code == 201).json()["id"]
        ap = await asyncio.gather(*[b.c.post(f"/v1/admin/freight/applications/{aid}/approve", headers=ADM)
                                    for _ in range(5)])
        assert codes(ap) == {200: 5}, [(r.status_code, r.text) for r in ap]
        assert len({r.json()["forwarder_id"] for r in ap}) == 1
        lst = (await b.c.get("/v1/admin/freight/forwarders", headers=ADM)).json()
        assert len(lst["items"]) == 1


async def test_approve_vs_reject_is_consistent(tmp_path):
    async with Boot(tmp_path) as b:
        aid = (await b.c.post("/v1/freight/applications", headers=uh("fx"), json=APP)).json()["id"]
        ap, rj = await asyncio.gather(
            b.c.post(f"/v1/admin/freight/applications/{aid}/approve", headers=ADM),
            b.c.post(f"/v1/admin/freight/applications/{aid}/reject", headers=ADM, json={"reason": "no docs"}))
        assert ap.status_code < 500 and rj.status_code < 500, (ap.text, rj.text)
        mine = (await b.c.get("/v1/freight/applications/mine", headers=uh("fx"))).json()["items"][0]
        fwd = (await b.c.get("/v1/admin/freight/forwarders", headers=ADM)).json()["items"]
        assert (mine["status"] == "approved") == (len(fwd) == 1)
        assert (ap.status_code == 200) == (mine["status"] == "approved")


async def test_unverified_or_suspended_forwarder_cannot_quote_or_win(tmp_path):
    async with Boot(tmp_path) as b:
        fid = await b.forwarder("fa")
        req = await b.request()
        r = await b.c.post(f"/v1/freight/requests/{req['id']}/quotes", headers=uh("nobody"), json=QUOTE)
        assert r.status_code == 403  # never approved
        qa = await b.quote(req["id"], "fa")
        sus = await b.c.post(f"/v1/admin/freight/forwarders/{fid}/suspend", headers=ADM, json={"reason": "bad actor"})
        assert sus.status_code == 200
        assert (await b.accept(qa["id"])).status_code == 409  # suspended after quoting: cannot be awarded


async def test_expired_quote_and_expired_request_cannot_be_accepted(tmp_path):
    async with Boot(tmp_path) as b:
        await b.forwarder("fa")
        req = await b.request()
        qa = await b.quote(req["id"], "fa", valid_days=1)
        b.clock.advance(days=2)
        rs = await asyncio.gather(*[b.accept(qa["id"]) for _ in range(3)])
        assert all(r.status_code == 409 for r in rs), [r.text for r in rs]
        assert (await b.req(req["id"]))["status"] in ("open", "expired")
        assert (await b.req(req["id"]))["awarded_quote_id"] is None


async def test_concurrent_double_rating_counts_once(tmp_path):
    async with Boot(tmp_path, rating_min_delay_seconds=0) as b:
        fid = await b.forwarder("fa")
        req = await b.request()
        qa = await b.quote(req["id"], "fa")
        await b.accept(qa["id"])
        await b.c.post(f"/v1/freight/requests/{req['id']}/close", headers=uh("buyer1"))
        rs = await asyncio.gather(*[b.c.post(f"/v1/freight/requests/{req['id']}/rating", headers=uh("buyer1"),
                                             json={"stars": 5}) for _ in range(5)])
        assert codes(rs)[201] == 1 and codes(rs)[409] == 4, [(r.status_code, r.text) for r in rs]
        f = (await b.c.get(f"/v1/freight/forwarders/{fid}", headers=uh("buyer1"))).json()
        assert f["rating"]["count"] == 1
