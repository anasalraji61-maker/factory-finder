#!/usr/bin/env python3
"""Focused cross-service end-to-end scenarios (edge cases the broad e2e scripts do not pin down).

    python scripts/e2e_scenarios.py     # boots the 15 local services (mock adapters, no network), runs 5 scenarios

  1. landed cost Shanghai->Baghdad through the gateway; geo sea route with avoid=suez changes; quotes label as_of/confidence
  2. tracking validate: a typo'd container number is invalid and returns suggestions
  3. payments: concurrent duplicate invoice creation yields exactly one invoice
  4. freight: a duplicate forwarder application answers 409
  5. feed: unliking a hidden post answers 404

Exit code is non-zero when any step fails. Not for remote stacks (needs local processes).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e  # noqa: E402
from e2e import ADMIN_TOKEN, GW, items, ok, step  # noqa: E402


def scenarios() -> None:
    c = httpx.Client(base_url=GW, timeout=30)
    sfx = uuid.uuid4().hex[:8]
    users: dict[str, str] = {}
    admin_h = {"X-Admin-Token": ADMIN_TOKEN}

    def h(role: str) -> dict:
        return {"Authorization": f"Bearer {users[role]}"}

    def register(role: str, patch_role: str):
        d = ok(c.post("/v1/auth/register", json={"email": f"sc{role}{sfx}@example.com", "password": "Passw0rd!x", "name": role.title()}), 201)
        users[role] = d["access_token"]
        ok(c.patch("/v1/me", headers=h(role), json={"role": patch_role}))

    step("setup: register buyer / supplier / reporter", lambda: [register("buyer", "buyer"), register("supplier", "supplier"), register("reporter", "buyer")])
    if len(users) < 3:
        return

    # ---- 1. landed cost + geo avoid=suez ---------------------------------------------------------
    def landed_and_avoid():
        q = ok(c.post("/v1/quotes/landed-cost", json={
            "goods": {"description": "chairs", "quantity": 500, "total_value": {"amount": "5000", "currency": "USD"},
                      "total_weight_kg": 3000, "total_volume_m3": 30},
            "origin": {"country_code": "CN", "city": "Shanghai"}, "destination": {"country_code": "IQ", "city": "Baghdad"},
            "display_currency": "USD"}))
        opts = q.get("options") or q.get("quotes")
        assert opts, str(q)[:200]
        for op in opts:
            assert op.get("lines"), f"{op.get('mode')}: no lines"
            for ln in op["lines"]:
                if ln["stage"] == "goods":
                    continue
                assert ln.get("as_of") and ln.get("source") and ln["amount"]["currency"], f"{op['mode']}: unlabelled line {ln}"
                assert ln["estimate"] is True and ln.get("range"), f"{op['mode']}: estimate without a range {ln}"
        assert q["created_at"] and any("FX" in a and "as of" in a for a in q["assumptions"]), q["assumptions"]
        assert any("confidence" in a for a in q["assumptions"]), "quote does not state duty-table confidence"
        prof = ok(c.get("/v1/compliance/countries/IQ"))["indicative"]
        assert prof["confidence"] in ("low", "medium", "high") and prof["as_of"] and prof["source"], prof
        # geo (through the gateway): Shanghai -> Rotterdam sea lane must change when suez is avoided
        p = {"from_lat": 31.23, "from_lon": 121.47, "to_lat": 51.95, "to_lon": 4.14, "mode": "sea"}
        base = ok(c.get("/v1/distance", params=p, headers=h("buyer")))
        alt = ok(c.get("/v1/distance", params={**p, "avoid": "suez"}, headers=h("buyer")))
        assert alt["distance_km"] > base["distance_km"], f"avoid=suez did not lengthen the route: {base['distance_km']} -> {alt['distance_km']}"
        assert "suez" in alt.get("avoided", []), alt
        assert c.get("/v1/distance", params={**p, "avoid": "nope"}, headers=h("buyer")).status_code == 422

    step("scenario 1: landed cost Shanghai->Baghdad labelled; geo avoid=suez changes the route", landed_and_avoid)

    # ---- 2. tracking validate typo ----------------------------------------------------------------
    def validate_typo():
        good = ok(c.get("/v1/validate/container/CSQU3054383", headers=h("buyer")))
        assert good["valid"] is True
        bad = ok(c.get("/v1/validate/container/CSQU3O54383", headers=h("buyer")))  # letter O typed for the digit 0
        assert bad["valid"] is False and bad["reason"], bad
        wrong_digit = ok(c.get("/v1/validate/container/CSQU3054384", headers=h("buyer")))
        assert wrong_digit["valid"] is False and wrong_digit["reason"] == "check_digit", wrong_digit
        assert bad["suggestions"], f"no suggestions for a typo'd container: {bad}"
        assert "CSQU3054383" in bad["suggestions"], bad["suggestions"]

    step("scenario 2: tracking validate typo'd container returns suggestions", validate_typo)

    # ---- 3. payments concurrent duplicate invoice -------------------------------------------------
    def concurrent_invoice():
        r = ok(c.post("/v1/requests", headers=h("buyer"), json={
            "kind": "product", "title": f"Scenario chairs {sfx}", "quantity": 100, "unit": "piece",
            "target_price": {"amount": "8", "currency": "USD"}, "destination": {"country_code": "IQ", "city": "Baghdad"}}), 201)
        o = ok(c.post(f"/v1/requests/{r['id']}/offers", headers=h("supplier"), json={
            "price": {"amount": "7.5", "currency": "USD"}, "supplier_name": "Supplier", "moq": 100, "lead_time_days": 20, "incoterm": "FOB"}), 201)
        a = ok(c.post(f"/v1/offers/{o['id']}/accept", headers=h("buyer")))
        did = (a.get("deal") or a).get("id")
        assert did, str(a)[:200]
        body = {"deal_id": did, "kind": "commission"}

        def post(_):
            with httpx.Client(base_url=GW, timeout=30) as cl:
                return cl.post("/v1/invoices", headers=h("buyer"), json=body)

        with ThreadPoolExecutor(8) as ex:
            rs = list(ex.map(post, range(8)))
        assert all(x.status_code in (200, 201) for x in rs), [(x.status_code, x.text[:120]) for x in rs]
        assert len({x.json()["id"] for x in rs}) == 1, f"{len({x.json()['id'] for x in rs})} distinct invoices from concurrent creates"
        mine = [i for i in items(ok(c.get("/v1/invoices", headers=h("buyer")))) if i.get("deal_id") == did]
        assert len(mine) == 1, f"{len(mine)} invoices stored for the deal"

    step("scenario 3: concurrent duplicate invoice creates yield one invoice", concurrent_invoice)

    # ---- 4. freight duplicate application ---------------------------------------------------------
    def freight_dup():
        body = {"company_name": f"Scenario Freight {sfx}", "country_code": "AE", "description": "Sea freight China to Iraq",
                "lanes": [{"origin_country": "CN", "destination_country": "IQ"}], "modes": ["sea"],
                "incoterms": ["FOB", "CIF"], "certifications": ["FIATA"]}
        ok(c.post("/v1/freight/applications", headers=h("supplier"), json=body), 201)
        r = c.post("/v1/freight/applications", headers=h("supplier"), json=body)
        assert r.status_code == 409, f"duplicate application -> {r.status_code} {r.text[:200]}"

    step("scenario 4: freight duplicate application returns 409", freight_dup)

    # ---- 5. feed unlike on a hidden post -----------------------------------------------------------
    def feed_unlike_hidden():
        d = items(ok(c.get("/v1/search", params={"q": "injection molding machine"})))
        sid = d[0]["supplier"]["id"]
        ok(c.patch("/v1/me", headers=h("supplier"), json={"supplier_id": sid}))
        rr = c.post(f"/v1/admin/supplier-claims/{ok(c.get('/v1/me', headers=h('supplier')))['id']}/approve", headers=admin_h)
        assert rr.status_code in (200, 204), f"claim approve {rr.status_code}"
        post = ok(c.post("/v1/feed/posts", headers=h("supplier"), json={"body": f"Scenario post {sfx}", "tags": ["sc"]}), 201)
        pid = post["id"]
        ok(c.put(f"/v1/feed/posts/{pid}/like", headers=h("buyer")))
        ok(c.post(f"/v1/admin/feed/posts/{pid}/hide", headers=admin_h, json={"reason": "scenario hide"}))
        for who in ("buyer", "reporter"):
            r = c.delete(f"/v1/feed/posts/{pid}/like", headers=h(who))
            assert r.status_code == 404, f"unlike on a hidden post as {who} -> {r.status_code} {r.text[:200]}"
        ok(c.post(f"/v1/admin/feed/posts/{pid}/restore", headers=admin_h))
        assert ok(c.delete(f"/v1/feed/posts/{pid}/like", headers=h("buyer")))["like_count"] == 0

    step("scenario 5: feed unlike on a hidden post returns 404", feed_unlike_hidden)


def main() -> int:
    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="ff-e2e-s-"))
    procs: list[subprocess.Popen] = []
    try:
        import os
        os.environ.update({"FF_FEED_ADMIN_TOKEN": ADMIN_TOKEN, "FF_FREIGHT_ADMIN_TOKEN": ADMIN_TOKEN})
        procs = e2e.start_services(tmp)
        e2e.wait_health(tmp)
        print("all services healthy")
        scenarios()
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        if any(not r[1] for r in e2e.RESULTS):
            for log in sorted(tmp.glob("*.log")):
                t = log.read_text(errors="replace")
                if "Traceback" in t:
                    print(f"--- {log.name} (tail)\n{t[-1200:]}")
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in e2e.RESULTS if not r[1]]
    print(f"\n{len(e2e.RESULTS) - len(failed)}/{len(e2e.RESULTS)} steps passed in {time.time() - t0:.0f}s")
    for name, _, msg in failed:
        print(f"FAILED: {name}\n        {msg}")
    return 1 if failed or not e2e.RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
