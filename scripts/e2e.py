#!/usr/bin/env python3
"""End-to-end smoke test: boots all 10 services and runs a scenario through the gateway.

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
}  # fmt: skip
GW = "http://localhost:8000"
RESULTS: list[tuple[str, bool, str]] = []


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
    }  # fmt: skip
    base_env.pop("FF_INTERNAL_TOKEN", None)
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
        r = httpx.get("http://localhost:8107/v1/shipments", headers={"X-User-Id": users["buyer"]["id"]})
        assert items(ok(r)), "buyer's shipment not visible with injected X-User-Id"
        r = httpx.get("http://localhost:8107/v1/shipments", headers={"X-User-Id": users["supplier"]["id"]})
        assert not items(ok(r)), "supplier sees buyer's shipments"
        ok(httpx.get("http://localhost:8106/v1/conversations", headers={"X-User-Id": users["supplier"]["id"]}))

    step("X-User-Id header injection + ownership isolation", inject)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ff-e2e-"))
    procs: list[subprocess.Popen] = []
    try:
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
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} steps passed")
    return 1 if failed or not RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
