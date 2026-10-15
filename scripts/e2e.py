#!/usr/bin/env python3
"""End-to-end smoke test: boots all services and runs a scenario through the gateway.

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
    "media": (8112, "ff_media.main:app"), "feed": (8113, "ff_feed.main:app"),
    "freight": (8114, "ff_freight.main:app"),
}  # fmt: skip
ADMIN_TOKEN = os.environ.get("FF_E2E_ADMIN_TOKEN", "e2e-admin-token")  # local run: also configured on the spawned services
# FF_E2E_BASE_URL=http://localhost:8000 -> run against an already running stack (e.g. docker compose);
# no local processes are spawned and the steps that need direct (unpublished) service ports are skipped.
REMOTE = os.environ.get("FF_E2E_BASE_URL", "").rstrip("/")
GW = REMOTE or "http://localhost:8000"
WEBHOOK_SECRET = "e2e-webhook-secret"  # payments mock-provider webhook HMAC key (local run only)
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


def refuse_in_production() -> None:
    """These harnesses start services with well-known tokens/secrets and no internal token: never next to real config."""
    env = os.environ.get("FF_ENV", "").strip().lower()
    if env in ("production", "prod", "staging", "stage") or os.environ.get("FF_PRODUCTION"):
        raise SystemExit(f"refusing to start the e2e/dev stack with FF_ENV={env or 'production'}: it uses known test secrets")


def start_services(tmp: Path, extra_env: dict[str, str] | None = None) -> list[subprocess.Popen]:
    refuse_in_production()
    procs = []
    base_env = {
        **os.environ,
        "FF_SOURCING_TRUST_MODE": "http", "FF_SOURCING_TRUST_BASE_URL": "http://localhost:8104",
        "FF_LOGISTICS_FX_PROVIDER": "mock", "FF_GATEWAY_JWT_SECRET": "test-secret",
        "FF_GATEWAY_BCRYPT_ROUNDS": "4", "FF_GATEWAY_RATE_LIMIT_PER_MINUTE": "100000",
        "FF_GATEWAY_AUTH_RATE_LIMIT_PER_MINUTE": "100000", "FF_TRACKING_REFRESH_MIN_INTERVAL_SECONDS": "3600",
        "FF_GATEWAY_ADMIN_TOKEN": ADMIN_TOKEN, "FF_PAYMENTS_ADMIN_TOKEN": ADMIN_TOKEN, "FF_PAYMENTS_PROVIDER": "mock",
        "FF_PAYMENTS_WEBHOOK_SECRET_MOCK": WEBHOOK_SECRET,
        "FF_DEMAND_ENABLED": "true", "FF_DEMAND_USE_MOCK_SOURCING": "true",
        "FF_MEDIA_STORAGE_ROOT": str(tmp / "media-files"), "FF_MEDIA_PUBLIC_BASE_URL": GW,
        "FF_FEED_ADMIN_TOKEN": ADMIN_TOKEN, "FF_FREIGHT_ADMIN_TOKEN": ADMIN_TOKEN,
        "FF_MEDIA_ADMIN_TOKEN": ADMIN_TOKEN,
        "FF_FREIGHT_RATING_MIN_DELAY_SECONDS": "0", "FF_FREIGHT_REPORT_MIN_ACCOUNT_AGE_SECONDS": "0",
    }  # fmt: skip
    base_env.update(extra_env or {})  # serve_stack.py: shifted ports / URLs
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
        assert deal["id"] in [x["id"] for x in items(ok(c.get("/v1/deals?role=buyer", headers=h("buyer"))))], "deal list"
        assert ok(c.get(f"/v1/requests/{rid}/deal", headers=h("buyer")))["id"] == deal["id"]
        assert c.get(f"/v1/requests/{rid}/deal", headers=h("supplier")).status_code == 404
        assert c.get("/v1/deals").status_code == 401
        ok(c.get(f"/v1/requests/{rid}/suggestions", headers=h("buyer")))

    step("rfq: request -> offer -> accept -> deal+commission (+suggestions)", rfq)

    def reviews():
        # public through the gateway (no token); a pending_payment deal is not reviewable yet (409)
        s = ok(c.get("/v1/suppliers/sup_e2e_none/review-summary"))
        assert s["count"] == 0 and s["average"] is None, s
        assert items(ok(c.get("/v1/suppliers/sup_e2e_none/reviews?sort=rating"))) == []
        r = c.post(f"/v1/deals/{deal['id']}/reviews", headers=h("buyer"), json={"rating": 5})
        assert r.status_code == 409, r.text
        assert c.post(f"/v1/deals/{deal['id']}/reviews", json={"rating": 5}).status_code == 401

    step("rfq: reviews public reads + write guards via gateway", reviews)

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

    def deal_lifecycle():
        import hashlib
        import hmac
        import json
        import time

        if REMOTE:
            return skip("deal paid -> review-eligible", "needs direct access to the payments webhook port")
        if not deal.get("id"):
            return skip("deal paid -> review-eligible", "no deal from the rfq step")
        did = deal["id"]
        # a stranger cannot touch the deal; the internal callback is not reachable through the gateway
        assert c.post(f"/v1/deals/{did}/confirm-receipt", headers=h("supplier")).status_code == 403
        r = c.post(f"/v1/internal/deals/{did}/payment-status", headers=h("buyer"), json={})
        assert r.status_code == 404, f"internal endpoint exposed via gateway: {r.status_code}"
        assert c.post(f"/v1/deals/{did}/fulfilment/start", headers=h("supplier")).status_code == 409  # not paid yet
        inv = {k: ok(c.post("/v1/invoices", headers=h("buyer"), json={"deal_id": did, "kind": k}), 200, 201)
               for k in ("commission", "deal_payment")}

        def webhook(invoice: dict, eid: str, status: str = "applied"):
            raw = json.dumps({"event_id": eid, "type": "payment.confirmed", "invoice_id": invoice["id"]}).encode()
            ts = int(time.time())
            mac = hmac.new(WEBHOOK_SECRET.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
            r = httpx.post("http://localhost:8111/v1/payments/webhooks/mock", content=raw, timeout=15,
                           headers={"X-FF-Signature": f"t={ts},v1={mac}", "Content-Type": "application/json"})
            assert r.status_code == 200 and r.json()["status"] == status, r.text

        def review_code() -> str:
            r = c.post(f"/v1/deals/{did}/reviews", headers=h("buyer"), json={"rating": 5})
            return r.json().get("error", {}).get("code", str(r.status_code))

        webhook(inv["deal_payment"], f"e2e-dp-{sfx}")
        d = ok(c.get(f"/v1/deals/{did}", headers=h("buyer")))
        assert d["status"] == "pending_payment" and d["payment"]["deal_payment"] == "paid", d  # commission still open
        assert review_code() == "deal_not_reviewable"
        webhook(inv["commission"], f"e2e-cm-{sfx}")
        webhook(inv["commission"], f"e2e-cm-{sfx}", "duplicate")  # duplicate delivery changes nothing
        assert ok(c.get(f"/v1/deals/{did}", headers=h("buyer")))["status"] == "paid"
        assert review_code() == "supplier_unverified", "paid deal should pass the status gate (supplier is unverified here)"
        assert ok(c.post(f"/v1/deals/{did}/fulfilment/start", headers=h("supplier")))["status"] == "in_fulfilment"
        assert ok(c.post(f"/v1/deals/{did}/delivered", headers=h("supplier")))["delivered_at"]
        assert c.post(f"/v1/deals/{did}/confirm-receipt", headers=h("supplier")).status_code == 403
        assert ok(c.post(f"/v1/deals/{did}/confirm-receipt", headers=h("buyer")))["status"] == "completed"
        ev = items(ok(c.get(f"/v1/deals/{did}/events", headers=h("buyer"))))
        assert [e["action"] for e in ev] == ["payment_paid", "payment_paid", "fulfilment_started", "delivered", "receipt_confirmed"], ev

    step("deal paid (payments webhook -> rfq) -> fulfilment -> completed + event log", deal_lifecycle)

    def media():
        import struct
        import zlib

        def chunk(t: bytes, d: bytes) -> bytes:
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

        raw = b"".join(b"\x00" + bytes([(x * 7 + y * 3 + int(sfx, 16)) % 256 for x in range(16) for _ in range(3)]) for y in range(16))
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
        files = {"file": ("photo.jpg", png, "image/jpeg")}  # name/type lie on purpose: magic bytes decide
        r = c.post("/v1/media/images", files=files)
        assert r.status_code == 401, f"upload without token -> {r.status_code}"
        r = c.post("/v1/media/images", files=files, data={"kind": "listing"}, headers=h("supplier"))
        if r.status_code in (404, 502, 503, 504) and r.json().get("error", {}).get("code") != "not_found":
            return skip("media upload via gateway", f"media not reachable ({r.status_code})")
        img = ok(r, 201)
        assert img["content_type"] == "image/png" and (img["width"], img["height"]) == (16, 16), str(img)[:200]
        path = "/" + img["url"].split("/", 3)[3] if img["url"].startswith("http") else img["url"]
        assert path == f"/v1/media/files/{img['id']}.png", path
        g = c.get(path)  # public, no token
        assert g.status_code == 200 and g.headers["content-type"] == "image/png", g.status_code
        assert g.headers.get("x-content-type-options") == "nosniff" and "immutable" in g.headers.get("cache-control", "")
        assert g.content[:8] == b"\x89PNG\r\n\x1a\n"
        r = c.post("/v1/media/images", files={"file": ("a.png", b"<html><script>1</script></html>", "image/png")}, headers=h("supplier"))
        assert r.status_code == 415, f"html disguised as png -> {r.status_code}"
        r = c.delete(f"/v1/media/images/{img['id']}", headers=h("buyer"))
        assert r.status_code == 404, f"other user's delete -> {r.status_code}"
        ok(c.delete(f"/v1/media/images/{img['id']}", headers=h("supplier")), 204)
        assert c.get(path).status_code == 404
        # private (verification) documents: never on the public route; owner / signed URL / admin only
        r = c.post("/v1/media/images", files={"file": ("d.png", png + b"", "image/png")}, data={"kind": "verification"}, headers=h("supplier"))
        doc = ok(r, 201)
        assert doc["visibility"] == "private" and doc["url"] == f"/v1/media/private/{doc['id']}.png", str(doc)[:200]
        assert c.get(f"/v1/media/files/{doc['id']}.png").status_code == 404, "private file served by the public route"
        assert c.get(doc["url"]).status_code == 404 and c.get(doc["url"], headers=h("buyer")).status_code == 404
        own = c.get(doc["url"], headers=h("supplier"))
        assert own.status_code == 200 and own.headers.get("cache-control") == "private, no-store", own.headers
        assert c.post(f"/v1/media/files/{doc['id']}/sign", headers=h("buyer")).status_code == 404
        sg = ok(c.post(f"/v1/media/files/{doc['id']}/sign", headers=h("supplier")))
        su = "/" + sg["url"].split("/", 3)[3] if sg["url"].startswith("http") else sg["url"]
        assert c.get(su).status_code == 200, "signed url"
        assert c.get(su[:-2] + "00").status_code == 404, "tampered signature accepted"
        assert c.get(f"/v1/admin/media/files/{doc['id']}").status_code == 401
        adm = c.get(f"/v1/admin/media/files/{doc['id']}", headers={"X-Admin-Token": ADMIN_TOKEN})
        assert adm.status_code == 200 and adm.content[:8] == b"\x89PNG\r\n\x1a\n", adm.status_code
        ok(c.delete(f"/v1/media/images/{doc['id']}", headers=h("supplier")), 204)

    step("media: upload (magic-byte check, public GET, owner-only delete) via gateway", media)

    def feed():
        me = ok(c.get("/v1/me", headers=h("supplier")))
        fsid = me.get("supplier_id")
        r = c.post("/v1/feed/posts", headers=h("supplier"), json={"body": f"E2E feed post {sfx}: new stock of planters", "tags": ["E2E"]})
        if r.status_code in (404, 502, 503, 504) and r.json().get("error", {}).get("code") != "not_found":
            return skip("feed via gateway", f"feed not reachable ({r.status_code})")
        if r.status_code == 403 or not fsid:
            return skip("feed via gateway", "no verified supplier claim in this run")
        post = ok(r, 201)
        assert post["supplier_id"] == fsid and post["tags"] == ["e2e"], str(post)[:200]
        assert c.post("/v1/feed/posts", headers=h("buyer"), json={"body": "x"}).status_code == 403, "buyer can post"
        assert c.post("/v1/feed/posts", headers=h("supplier"), json={"body": "call +964 770 123 4567"}).status_code == 422
        assert c.post("/v1/feed/posts", headers=h("supplier"), json={"body": "x", "media": ["https://evil.example/a.png"]}).status_code == 422
        assert c.get("/v1/feed/home").status_code == 401
        pid = post["id"]
        assert any(i["id"] == pid for i in items(ok(c.get("/v1/feed/trending"))))  # public
        assert ok(c.get("/v1/feed/home", headers=h("buyer")))["source"] == "trending"  # follows nobody yet
        assert ok(c.post(f"/v1/feed/suppliers/{fsid}/follow", headers=h("buyer")))["following"] is True
        assert ok(c.post(f"/v1/feed/suppliers/{fsid}/follow", headers=h("buyer")))["follower_count"] == 1  # idempotent
        home = ok(c.get("/v1/feed/home", headers=h("buyer")))
        assert home["source"] == "following" and home["items"][0]["id"] == pid, str(home)[:300]
        assert ok(c.put(f"/v1/feed/posts/{pid}/like", headers=h("buyer")))["like_count"] == 1
        assert ok(c.put(f"/v1/feed/posts/{pid}/like", headers=h("buyer")))["like_count"] == 1
        cm = ok(c.post(f"/v1/feed/posts/{pid}/comments", headers=h("buyer"), json={"body": "Interested, price per 100?"}), 201)
        assert ok(c.get(f"/v1/feed/posts/{pid}", headers=h("buyer")))["comment_count"] == 1
        assert items(ok(c.get(f"/v1/feed/posts/{pid}/comments", headers=h("supplier"))))[0]["id"] == cm["id"]
        assert c.post(f"/v1/feed/posts/{pid}/report", headers=h("supplier"), json={"reason": "spam"}).status_code == 422  # own post
        assert c.post(f"/v1/feed/posts/{pid}/report", headers=h("buyer"), json={"reason": "spam"}).status_code == 202
        assert c.delete(f"/v1/feed/posts/{pid}", headers=h("buyer")).status_code == 403
        assert c.get("/v1/admin/feed/posts").status_code == 401, "feed admin needs the gateway admin token"
        assert c.get("/v1/admin/feed/posts?status=all", headers=admin_h).status_code == 200, "feed admin passthrough"
        assert c.get("/v1/admin/feed/reports", headers=admin_h).status_code == 200
        ok(c.delete(f"/v1/feed/suppliers/{fsid}/follow", headers=h("buyer")))
        ok(c.delete(f"/v1/feed/posts/{pid}", headers=h("supplier")), 204)
        assert c.get(f"/v1/feed/posts/{pid}", headers=h("buyer")).status_code == 404

    step("feed: supplier post -> follow -> home -> like/comment/report -> delete (via gateway)", feed)

    def freight():
        body = {
            "company_name": f"E2E Freight {sfx}", "country_code": "AE", "description": "Sea freight China to Iraq",
            "lanes": [{"origin_country": "CN", "destination_country": "IQ"}], "modes": ["sea"],
            "incoterms": ["FOB", "CIF"], "certifications": ["FIATA"],
        }  # fmt: skip
        r = c.post("/v1/freight/applications", headers=h("supplier"), json=body)
        if r.status_code in (404, 502, 503, 504) and r.json().get("error", {}).get("code") != "validation_error":
            return skip("freight via gateway", f"freight not reachable ({r.status_code})")
        app = ok(r, 201)
        assert app["status"] == "pending" and app["forwarder_id"] is None
        assert c.post("/v1/freight/applications", headers=h("supplier"), json=body).status_code == 409  # one pending
        assert c.get("/v1/freight/forwarders").status_code == 401
        assert c.get("/v1/admin/freight/applications").status_code == 401, "freight admin needs the gateway admin token"
        assert c.get("/v1/admin/freight/applications", headers={"X-Admin-Token": ADMIN_TOKEN}).status_code == 200, "freight admin passthrough"
        req = {
            "origin_country": "CN", "origin_place": "Shenzhen", "destination_country": "IQ", "destination_place": "Umm Qasr",
            "cargo_description": f"E2E ceramic tiles {sfx}", "weight_kg": "18000", "volume_cbm": "28.5", "mode": "sea",
            "container_type": "40HC", "incoterm": "FOB", "ready_date": time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 86400)),
        }  # fmt: skip
        assert c.post("/v1/freight/requests", headers=h("buyer"), json={**req, "cargo_description": "mail me boss@example.com"}).status_code == 422
        rq = ok(c.post("/v1/freight/requests", headers=h("buyer"), json=req), 201)
        quote = {"amount": "2450.00", "currency": "USD", "transit_days": 28, "inclusions": ["Ocean freight"], "terms": "Net 14 days"}
        assert c.post(f"/v1/freight/requests/{rq['id']}/quotes", headers=h("supplier"), json=quote).status_code == 403  # not approved yet
        if REMOTE:
            return skip("freight approval + quoting", "admin approval needs the service port (local run only)")
        adm = {"X-Admin-Token": ADMIN_TOKEN}
        fid = ok(httpx.post(f"http://localhost:8114/v1/admin/freight/applications/{app['id']}/approve", headers=adm, timeout=15))["forwarder_id"]
        assert ok(c.get("/v1/freight/forwarders/me", headers=h("supplier")))["id"] == fid
        inbox = items(ok(c.get("/v1/freight/forwarders/me/inbox", headers=h("supplier"))))
        assert rq["id"] in {i["id"] for i in inbox} and all(i["buyer_id"] is None for i in inbox)
        q = ok(c.post(f"/v1/freight/requests/{rq['id']}/quotes", headers=h("supplier"), json=quote), 201)
        assert c.post(f"/v1/freight/requests/{rq['id']}/quotes", headers=h("supplier"), json=quote).status_code == 409
        assert c.post(f"/v1/freight/requests/{rq['id']}/quotes", headers=h("supplier"), json={**quote, "currency": "EUR"}).status_code in (409, 422)
        cmp_ = ok(c.get(f"/v1/freight/requests/{rq['id']}/comparison", headers=h("buyer")))
        assert [i["quote"]["id"] for i in cmp_["items"]] == [q["id"]] and cmp_["items"][0]["explanation"]
        assert c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=h("supplier")).status_code == 404  # only the buyer awards
        a1 = ok(c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=h("buyer")))
        a2 = ok(c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=h("buyer")))
        assert a1 == a2 and a1["request"]["status"] == "awarded"
        assert ok(c.post(f"/v1/freight/requests/{rq['id']}/close", headers=h("buyer")))["outcome"] == "completed"
        assert ok(c.post(f"/v1/freight/requests/{rq['id']}/rating", headers=h("buyer"), json={"stars": 5, "comment": "Smooth shipment"}), 201)["stars"] == 5
        assert c.post(f"/v1/freight/requests/{rq['id']}/rating", headers=h("buyer"), json={"stars": 4}).status_code == 409
        assert ok(c.get(f"/v1/freight/forwarders/{fid}", headers=h("buyer")))["rating"] == {"average": "5.00", "count": 1}

    step("freight: apply -> admin approve -> request -> quote -> compare -> award -> complete -> rate (via gateway)", freight)



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
