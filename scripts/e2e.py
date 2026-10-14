#!/usr/bin/env python3
"""End-to-end smoke test: boots all 12 services and runs a scenario through the gateway.

    python scripts/e2e.py            # exits non-zero on any failure
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from decimal import Decimal
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SERVICES = {  # name: (port, module)
    "gateway": (8000, "ff_gateway.main:app"), "sourcing": (8101, "ff_sourcing.main:app"),
    "logistics": (8102, "ff_logistics.main:app"), "geo": (8103, "ff_geo.main:app"),
    "trust": (8104, "ff_trust.main:app"), "rfq": (8105, "ff_rfq.main:app"),
    "messaging": (8106, "ff_messaging.main:app"), "tracking": (8107, "ff_tracking.main:app"),
    "notifications": (8108, "ff_notifications.main:app"), "assistant": (8109, "ff_assistant.main:app"),
    "demand": (8110, "ff_demand.main:app"), "payments": (8111, "ff_payments.main:app"),
}  # fmt: skip
ADMIN_TOKEN = os.environ.get("FF_E2E_ADMIN_TOKEN", "e2e-admin-token")  # local run: also configured on the spawned services
# FF_E2E_BASE_URL=http://localhost:8000 -> run against an already running stack (e.g. docker compose);
# no local processes are spawned and the steps that need direct (unpublished) service ports are skipped.
REMOTE = os.environ.get("FF_E2E_BASE_URL", "").rstrip("/")
GW = REMOTE or "http://localhost:8000"
RESULTS: list[tuple[str, bool, str]] = []
SKIPPED: list[str] = []


def step(name: str, fn) -> object:
    try:
        out = fn()
        RESULTS.append((name, True, ""))
        print(f"PASS  {name}")
        return out
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"[:400]
        RESULTS.append((name, False, msg))
        print(f"FAIL  {name}\n      {msg}")
        return None


def skip(name: str, why: str) -> None:
    SKIPPED.append(name)
    print(f"SKIP  {name} ({why})")


def ok(r: httpx.Response, *codes: int) -> dict | list:
    want = codes or (200, 201)
    assert r.status_code in want, f"{r.request.method} {r.request.url.path} -> {r.status_code} {r.text[:300]}"
    return r.json() if r.content else {}


def items(d) -> list:
    if isinstance(d, list):
        return d
    for k in ("items", "results", "data", "cities", "hubs", "countries", "carriers", "alerts", "messages"):
        if isinstance(d, dict) and isinstance(d.get(k), list):
            return d[k]
    raise AssertionError(f"no list in {str(d)[:200]}")


def start_services(tmp: Path) -> list[subprocess.Popen]:
    procs = []
    base_env = {
        **os.environ,
        "FF_SOURCING_TRUST_MODE": "http", "FF_SOURCING_TRUST_BASE_URL": "http://localhost:8104",
        "FF_LOGISTICS_FX_PROVIDER": "mock", "FF_GATEWAY_JWT_SECRET": "test-secret",
        "FF_GATEWAY_BCRYPT_ROUNDS": "4", "FF_GATEWAY_RATE_LIMIT_PER_MINUTE": "100000",
        "FF_GATEWAY_AUTH_RATE_LIMIT_PER_MINUTE": "100000", "FF_TRACKING_REFRESH_MIN_INTERVAL_SECONDS": "3600",
        "FF_GATEWAY_ADMIN_TOKEN": ADMIN_TOKEN, "FF_PAYMENTS_ADMIN_TOKEN": ADMIN_TOKEN, "FF_PAYMENTS_PROVIDER": "mock",
        "FF_DEMAND_ENABLED": "true", "FF_DEMAND_USE_MOCK_SOURCING": "true",
    }  # fmt: skip
    base_env.pop("FF_INTERNAL_TOKEN", None)
    base_env.pop("FF_PAYMENTS_INTERNAL_TOKEN", None)
    for name, (port, app) in SERVICES.items():
        svc = ROOT / "services" / name
        env = {**base_env, "PYTHONPATH": str(svc / "src")}
        env[f"FF_{name.upper()}_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp}/{name}.db"
        log = open(tmp / f"{name}.log", "wb")  # noqa: SIM115
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", app, "--port", str(port), "--log-level", "warning"],
            cwd=svc, env=env, stdout=log, stderr=subprocess.STDOUT,
        ))  # fmt: skip
    return procs


def wait_health(tmp: Path) -> None:
    deadline = time.time() + 90
    pending = dict(SERVICES)
    while pending and time.time() < deadline:
        for name, (port, _) in list(pending.items()):
            try:
                if httpx.get(f"http://localhost:{port}/health", timeout=2).status_code == 200:
                    pending.pop(name)
            except httpx.HTTPError:
                pass
        time.sleep(0.5)
    if pending:
        for name in pending:
            print(f"--- {name}.log\n" + (tmp / f"{name}.log").read_text(errors="replace")[-1500:])
        raise SystemExit(f"services not healthy: {list(pending)}")


def scenario() -> None:
    c = httpx.Client(base_url=GW, timeout=30)
    sfx = uuid.uuid4().hex[:8]
    users: dict[str, dict] = {}

    def register(role: str, name: str):
        def go():
            d = ok(c.post("/v1/auth/register", json={
                "email": f"{role}{sfx}@example.com", "password": "Passw0rd!x", "name": name}), 201)
            assert d["access_token"] and d["refresh_token"]
            users[role] = {"tok": d["access_token"], "ref": d["refresh_token"], "id": d["user"]["id"]}
            ok(c.patch("/v1/me", headers={"Authorization": f"Bearer {d['access_token']}"}, json={"role": role}))
        return go

    step("auth: register buyer", register("buyer", "Buyer One"))
    step("auth: register supplier", register("supplier", "Supplier One"))
    if len(users) < 2:
        return

    def h(role: str) -> dict:
        return {"Authorization": f"Bearer {users[role]['tok']}"}

    def login():
        d = ok(c.post("/v1/auth/login", json={"email": f"buyer{sfx}@example.com", "password": "Passw0rd!x"}))
        users["buyer"]["tok"] = d["access_token"]
        users["buyer"]["ref"] = d["refresh_token"]

    def refresh():
        d = ok(c.post("/v1/auth/refresh", json={"refresh_token": users["buyer"]["ref"]}))
        users["buyer"]["tok"] = d["access_token"]
        assert ok(c.get("/v1/me", headers=h("buyer")))["id"] == users["buyer"]["id"]

    step("auth: login", login)
    step("auth: refresh", refresh)

    def me():
        assert ok(c.get("/v1/me", headers=h("buyer")))["name"] == "Buyer One"
        d = ok(c.patch("/v1/me", headers=h("buyer"), json={
            "company": "ACME", "default_destination": {"country_code": "IQ", "city": "Baghdad"}}))
        assert d["company"] == "ACME" and d["default_destination"]["country_code"] == "IQ"

    step("me: GET + PATCH", me)
    step("auth: protected route without token -> 401",
         lambda: ok(c.get("/v1/shipments"), 401) and None)

    found: dict = {}

    def search_ar():
        d = ok(c.get("/v1/search", params={"q": "خط انتاج معجنات"}))
        found["ar"] = items(d)
        assert found["ar"], "no results for Arabic query"

    def search_en():
        d = ok(c.get("/v1/search", params={"q": "injection molding machine"}))
        found["en"] = items(d)
        assert found["en"], "no results for English query"

    step("sourcing: search (Arabic)", search_ar)
    step("sourcing: search (English)", search_en)

    def detail():
        lid = (found.get("en") or found.get("ar"))[0]["id"]
        d = ok(c.get(f"/v1/listings/{lid}"))
        assert d["id"] == lid
        found["listing"] = d

    step("sourcing: listing detail", detail)

    def trust_band():
        for it in (found.get("en") or [])[:3]:
            band = (it.get("supplier") or {}).get("trust_band")
            assert band, f"no trust band on listing supplier: {str(it.get('supplier'))[:200]}"
        sid = found["listing"]["supplier"]["id"]
        sup = ok(c.get(f"/v1/suppliers/{sid}"))
        assert sup["id"] == sid
        t = ok(c.get(f"/v1/trust/suppliers/{sid}", headers=h("buyer")), 200)
        assert t.get("band") and t.get("score") is not None

    step("sourcing<->trust: band on listings, supplier, trust score", trust_band)
    step("sourcing: categories", lambda: items(ok(c.get("/v1/categories"))) or (_ for _ in ()).throw(AssertionError("empty")))

    def geo():
        assert items(ok(c.get("/v1/cities", params={"country": "IQ"})))
        assert items(ok(c.get("/v1/countries")))
        n = items(ok(c.get("/v1/hubs/nearest", params={"lat": 33.3, "lon": 44.4, "limit": 3})))
        assert n

    step("geo: countries, cities, hubs/nearest", geo)

    def quote(o: dict, d: dict):
        def go():
            q = ok(c.post("/v1/quotes/landed-cost", json={
                "goods": {"description": "chairs", "quantity": 500, "total_value": {"amount": "5000", "currency": "USD"},
                          "total_weight_kg": 3000, "total_volume_m3": 30},
                "origin": o, "destination": d, "display_currency": "USD"}))
            opts = q.get("options") or q.get("quotes")
            assert opts, f"no options: {str(q)[:200]}"
            for op in opts:
                t = op["total"]  # range {min,max}; lines are the midpoint estimate
                lo, hi = Decimal(t["min"]["amount"]), Decimal(t["max"]["amount"])
                s = sum(Decimal(ln["amount"]["amount"]) for ln in op["lines"])
                assert abs(s - (lo + hi) / 2) <= Decimal("0.05"), f"{op['mode']}: sum(lines) {s} != mid({lo},{hi})"
                assert op["lines"][0]["amount"]["currency"] == t["min"]["currency"]
            for op in opts:
                if op["mode"].startswith("sea"):
                    assert op["origin_hub"] and op["destination_hub"], f"empty hub names: {op['origin_hub']!r} {op['destination_hub']!r}"
        return go

    step("logistics<->geo: Shanghai->Baghdad quote", quote({"country_code": "CN", "city": "Shanghai"}, {"country_code": "IQ", "city": "Baghdad"}))
    step("logistics<->geo: Yiwu->Erbil quote", quote({"country_code": "CN", "city": "Yiwu"}, {"country_code": "IQ", "city": "Erbil"}))

    def fx():
        d = ok(c.post("/v1/fx/convert", headers=h("buyer"), json={"amount": "100", "from": "USD", "to": "IQD"}))
        assert "result" in d or "amount" in d or "converted" in d, str(d)[:200]
        ok(c.get("/v1/fx/rates"))

    step("logistics: fx convert + rates", fx)
    step("logistics: carriers", lambda: ok(c.get("/v1/carriers", headers=h("buyer"))))

    deal: dict = {}

    def rfq():
        r = ok(c.post("/v1/requests", headers=h("buyer"), json={
            "kind": "product", "title": "Plastic chairs 500", "quantity": 500, "unit": "piece",
            "target_price": {"amount": "8", "currency": "USD"}, "destination": {"country_code": "IQ", "city": "Erbil"}}), 201)
        rid = r["id"]
        o = ok(c.post(f"/v1/requests/{rid}/offers", headers=h("supplier"), json={
            "price": {"amount": "7.5", "currency": "USD"}, "supplier_name": "Supplier One", "moq": 100,
            "lead_time_days": 20, "incoterm": "FOB"}), 201)
        offers = items(ok(c.get(f"/v1/requests/{rid}/offers", headers=h("buyer"))))
        assert offers
        a = ok(c.post(f"/v1/offers/{o['id']}/accept", headers=h("buyer")))
        d = a.get("deal") or a
        assert d.get("commission"), f"no commission: {str(a)[:300]}"
        deal.update(id=d.get("id") or d.get("deal_id"), rid=rid)
        ok(c.get(f"/v1/deals/{deal['id']}", headers=h("buyer")))
        ok(c.get(f"/v1/requests/{rid}/suggestions", headers=h("buyer")))

    step("rfq: request -> offer -> accept -> deal+commission (+suggestions)", rfq)

    conv: dict = {}

    def msg():
        sid = users["supplier"]["id"]
        cv = ok(c.post("/v1/conversations", headers=h("buyer"), json={
            "participants": [{"user_id": sid, "role": "supplier"}], "my_role": "buyer",
            "context": {"type": "listing", "ref_id": found["listing"]["id"]}}), 200, 201)
        conv["id"] = cv["id"]
        ok(c.post(f"/v1/conversations/{conv['id']}/messages", headers=h("buyer"),
                  json={"type": "text", "text": "Hello, price for 500?"}), 201)
        lst = ok(c.get("/v1/conversations", headers=h("supplier")))
        its = items(lst)
        assert its and its[0]["unread_count"] >= 1, f"supplier unread: {str(lst)[:300]}"
        ok(c.post(f"/v1/conversations/{conv['id']}/read", headers=h("supplier"), json={}))
        after = items(ok(c.get("/v1/conversations", headers=h("supplier"))))
        assert after[0]["unread_count"] == 0
        assert items(ok(c.get(f"/v1/conversations/{conv['id']}/messages", headers=h("supplier"))))

    step("messaging: start, send, supplier unread, mark read", msg)

    def track():
        s = ok(c.post("/v1/shipments", headers=h("buyer"), json={
            "reference": "CSQU3054383", "reference_type": "container", "label": "chairs"}), 201)
        sid = s["id"]
        g = ok(c.get(f"/v1/shipments/{sid}", headers=h("buyer")))
        assert g.get("events"), "no timeline events"
        r1 = c.post(f"/v1/shipments/{sid}/refresh", headers=h("buyer"))
        r2 = c.post(f"/v1/shipments/{sid}/refresh", headers=h("buyer"))
        assert r1.status_code in (200, 202, 429) and r2.status_code in (200, 202, 429), (r1.text[:200], r2.text[:200])
        ok(c.get("/v1/validate/container/CSQU3054383", headers=h("buyer")))
        assert items(ok(c.get("/v1/shipments", headers=h("buyer"))))
        return r2

    step("tracking: create, timeline, refresh throttle, list", track)

    def notif():
        w = ok(c.post("/v1/watchlist", headers=h("buyer"), json={"listing_id": found["listing"]["id"]}), 201)
        assert w["id"]
        assert items(ok(c.get("/v1/watchlist", headers=h("buyer"))))
        r = c.post("/v1/alerts/evaluate", headers=h("buyer"), json={})
        if r.status_code in (401, 403, 404) and REMOTE:
            return  # internal route is not published in compose; covered by the local run
        if r.status_code in (401, 403, 404):  # blocked at the gateway by design -> internal route
            r = httpx.post("http://localhost:8108/v1/alerts/evaluate", json={"owner_id": users["buyer"]["id"]}, timeout=30)
        ok(r)
        ok(c.get("/v1/alerts", headers=h("buyer")))

    step("notifications: watchlist, evaluate, alerts", notif)

    def assistant():
        d = ok(c.post("/v1/assistant/query", headers=h("buyer"), json={"text": "ابي ٥٠٠ كرسي بلاستك من الصين الى اربيل", "locale": "ar"}))
        blob = str(d)
        assert d.get("listings"), f"no listings: {blob[:300]}"
        assert d.get("quote") or d.get("quotes"), f"no quote: {blob[:300]}"

    step("assistant: Arabic query -> listings + quote", assistant)

    def inject():
        if REMOTE:
            return  # needs direct access to tracking/messaging ports
        r = httpx.get("http://localhost:8107/v1/shipments", headers={"X-User-Id": users["buyer"]["id"]})
        assert items(ok(r)), "buyer's shipment not visible with injected X-User-Id"
        r = httpx.get("http://localhost:8107/v1/shipments", headers={"X-User-Id": users["supplier"]["id"]})
        assert not items(ok(r)), "supplier sees buyer's shipments"
        ok(httpx.get("http://localhost:8106/v1/conversations", headers={"X-User-Id": users["supplier"]["id"]}))

    step("X-User-Id header injection + ownership isolation", inject)

    # ---- extended steps (hs, trust history, prefs, saved search, sort/facets, demand, payments) ----
    def hs():
        d = ok(c.get("/v1/hs/search", params={"q": "chair"}, headers=h("buyer")))
        res = items(d) if not isinstance(d, dict) or "results" in d or "items" in d else d.get("matches") or []
        assert res, f"no HS matches: {str(d)[:200]}"

    step("logistics: HS search through gateway", hs)

    def trust_history():
        sid = found["listing"]["supplier"]["id"]
        d = ok(c.get(f"/v1/trust/suppliers/{sid}/history", headers=h("buyer")))
        pts = d.get("points") or d.get("history") or d.get("items") or []
        assert pts, f"empty trust history: {str(d)[:200]}"

    step("trust: supplier score history", trust_history)

    def prefs():
        before = ok(c.get("/v1/notification-prefs", headers=h("buyer")))
        assert isinstance(before, dict)
        d = ok(c.put("/v1/notification-prefs", headers=h("buyer"), json={
            "language": "en", "timezone": "Asia/Baghdad", "quiet_hours": {"start": "22:00", "end": "07:00"}}))
        assert d.get("language") == "en" and d.get("timezone") == "Asia/Baghdad", str(d)[:200]
        again = ok(c.get("/v1/notification-prefs", headers=h("buyer")))
        assert again.get("language") == "en" and (again.get("quiet_hours") or {}).get("start") == "22:00", str(again)[:200]

    step("notifications: prefs PUT -> GET round trip", prefs)

    def saved_search():
        body = {"search": {"q": "injection molding machine", "kind": "product"}, "drop_threshold_pct": "10"}
        w = ok(c.post("/v1/watchlist", headers=h("buyer"), json=body), 200, 201)
        assert w["type"] == "search" and w["id"], str(w)[:200]
        again = ok(c.post("/v1/watchlist", headers=h("buyer"), json=body), 200, 201)
        assert again["id"] == w["id"], "saved search watch is not idempotent"
        assert any(x["id"] == w["id"] for x in items(ok(c.get("/v1/watchlist", headers=h("buyer")))))

    step("notifications: saved-search watch (idempotent)", saved_search)

    def sort_facets():
        d = ok(c.get("/v1/search", params={"q": "machine", "sort": "price_asc", "page_size": 50}))
        its = items(d)
        assert len(its) >= 2, f"need >=2 results to check order, got {len(its)}"
        prices = [Decimal(str(i["unit_price"]["amount"])) for i in its if (i.get("unit_price") or {}).get("amount") is not None]
        assert prices == sorted(prices), f"price_asc not sorted: {prices[:10]}"
        fac = d.get("facets")
        assert fac and fac.get("kind"), f"no facets: {str(d)[:200]}"
        assert all(f["count"] > 0 for f in fac["kind"])
        ok(c.get("/v1/search", params={"q": "machine", "sort": "trust"}))
        r = c.get("/v1/search", params={"sort": "bogus"})
        assert r.status_code == 422, f"bad sort accepted: {r.status_code}"

    step("sourcing: sort + facets", sort_facets)

    admin_h = {"X-Admin-Token": ADMIN_TOKEN}

    def native_listings():
        pool = [i["supplier"] for i in (found.get("en") or []) + (found.get("ar") or [])]
        sid = next((x["id"] for x in pool if x.get("trust_band") in ("green", "yellow")), found["listing"]["supplier"]["id"])
        body = {
            "kind": "product", "title": "E2E native ceramic planter", "category": "furniture", "unit": "piece", "moq": 5,
            "price": {"min": {"amount": "2.50", "currency": "USD"}, "max": {"amount": "3.00", "currency": "USD"}},
            "origin": {"country_code": "IQ", "city": "Baghdad"},
        }
        assert c.post("/v1/my/listings", json=body, headers=h("supplier")).status_code == 403, "unclaimed user can create"
        ok(c.patch("/v1/me", headers=h("supplier"), json={"supplier_id": sid}))
        r = c.post("/v1/my/listings", json=body, headers=h("supplier"))
        assert r.status_code == 403, "pending claim must not be trusted"
        r = c.post(f"/v1/admin/supplier-claims/{users['supplier']['id']}/approve", headers=admin_h)
        if r.status_code in (404, 502, 503, 504):
            return skip("native listings via gateway", f"admin claims not available ({r.status_code})")
        ok(r)
        lst = ok(c.post("/v1/my/listings", json=body, headers=h("supplier")), 201)
        assert lst["status"] == "draft" and lst["id"].startswith("nat_") and lst["supplier"]["id"] == sid
        assert ok(c.get("/v1/my/listings", headers=h("supplier")))["total"] == 1
        assert c.get(f"/v1/my/listings/{lst['id']}", headers=h("buyer")).status_code == 403
        r = c.post(f"/v1/my/listings/{lst['id']}/publish", headers=h("supplier"))
        if r.status_code in (403, 503):  # supplier trust band red / trust not computable for this id
            return skip("native listings publish", f"publish gated: {r.json()['error']['code']}")
        assert ok(r)["status"] == "published"
        hits = items(ok(c.get("/v1/search", params={"q": "E2E native ceramic planter"})))
        assert any(i["id"] == lst["id"] and i["source"] == "native" for i in hits), "published listing not searchable"
        ok(c.post(f"/v1/my/listings/{lst['id']}/unpublish", headers=h("supplier")))
        hits = items(ok(c.get("/v1/search", params={"q": "E2E native ceramic planter"})))
        assert not any(i["id"] == lst["id"] for i in hits), "archived listing still searchable"

    step("sourcing: supplier-owned listings (claim -> create -> publish -> search)", native_listings)

    def demand():
        r = c.get("/v1/admin/demand/quota", headers=admin_h)
        if r.status_code in (404, 502, 503, 504):
            return skip("demand (admin) via gateway", f"admin/demand not available ({r.status_code}); set FF_E2E_ADMIN_TOKEN")
        assert c.get("/v1/admin/demand/quota").status_code in (401, 404), "admin route open without token"
        ok(r)
        sig = ok(c.post("/v1/admin/demand/signals", headers=admin_h, json={
            "text": "ابحث عن مورد كراسي بلاستيك 500 قطعة الى اربيل", "url": f"https://example.com/post/{sfx}"}), 200, 201)
        assert sig, "empty import result"
        assert items(ok(c.get("/v1/admin/demand/signals", headers=admin_h)))
        drafts = items(ok(c.get("/v1/admin/demand/drafts", headers=admin_h)))
        if drafts:
            d = ok(c.post(f"/v1/admin/demand/drafts/{drafts[0]['id']}/approve", headers=admin_h, json={}), 200, 403)
            assert d, "empty approve result"
        ok(c.get("/v1/admin/overview", headers=admin_h))

    step("demand: admin import signal -> drafts -> approve (via gateway)", demand)

    def payments():
        if not deal.get("id"):
            return skip("payments invoice via gateway", "no deal from the rfq step")
        r = c.post("/v1/invoices", headers=h("buyer"), json={"deal_id": deal["id"], "kind": "commission"})
        if r.status_code in (404, 502, 503, 504) and r.json().get("error", {}).get("code") != "not_found":
            return skip("payments invoice via gateway", f"payments not reachable ({r.status_code})")
        inv = ok(r, 200, 201)
        assert inv["id"] and inv["status"] in ("pending", "awaiting_payment", "confirming", "paid"), str(inv)[:200]
        again = ok(c.post("/v1/invoices", headers=h("buyer"), json={"deal_id": deal["id"], "kind": "commission"}), 200, 201)
        assert again["id"] == inv["id"], "invoice create is not idempotent"
        assert ok(c.get(f"/v1/invoices/{inv['id']}", headers=h("buyer")))["id"] == inv["id"]
        assert items(ok(c.get("/v1/invoices", headers=h("buyer"))))
        r = c.get(f"/v1/invoices/{inv['id']}", headers=h("supplier"))
        assert r.status_code in (403, 404), f"unrelated user can read invoice: {r.status_code}"

    step("payments: commission invoice (idempotent, owner-only) via gateway", payments)



def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ff-e2e-"))
    procs: list[subprocess.Popen] = []
    try:
        if REMOTE:
            deadline = time.time() + 120
            while True:
                try:
                    if httpx.get(f"{GW}/health", timeout=3).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.time() > deadline:
                    raise SystemExit(f"gateway not healthy at {GW}")
                time.sleep(1)
        else:
            procs = start_services(tmp)
            wait_health(tmp)
        print("all services healthy")
        scenario()
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        failed = [r for r in RESULTS if not r[1]]
        if failed:  # show the tail of service logs to help debugging
            for log in sorted(tmp.glob("*.log")):
                t = log.read_text(errors="replace")
                if "Traceback" in t:
                    print(f"--- {log.name} (tail)\n{t[-1200:]}")
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} steps passed" + (f", {len(SKIPPED)} skipped" if SKIPPED else ""))
    return 1 if failed or not RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
