#!/usr/bin/env python3
"""Boot the whole local stack (same services/env as scripts/e2e.py), seed minimal data through the
gateway, write a JSON info file and keep running until killed. Used by the mobile live-contract tests.

    python scripts/serve_stack.py            # prints READY once healthy + seeded
    FF_STACK_PORT=18000 FF_STACK_INFO=/tmp/ff_stack.json python scripts/serve_stack.py

FF_STACK_PORT is the gateway port (default 8000); every other service is shifted by the same offset
and the cross-service URLs are rewired, so a second stack can run next to a dev stack.
Seeding is best effort: a failed seed step is listed under "seed_errors" in the info file.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import struct
import sys
import tempfile
import time
import uuid
import zlib
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e  # noqa: E402  (reuse SERVICES, start_services, wait_health, ok, items)
from e2e import ADMIN_TOKEN, items, ok  # noqa: E402

BASE_PORT = int(os.environ.get("FF_STACK_PORT", "8000"))
INFO_PATH = Path(os.environ.get("FF_STACK_INFO", "/tmp/ff_stack.json"))
PASSWORD = "Passw0rd!x"
OFFSET = BASE_PORT - 8000
GW = f"http://localhost:{BASE_PORT}"


def shift_ports() -> dict[str, str]:
    """Move every service by OFFSET (mutates e2e.SERVICES) and return the env that rewires URLs."""
    for name, (port, app) in list(e2e.SERVICES.items()):
        e2e.SERVICES[name] = (port + OFFSET, app)

    def url(name: str) -> str:
        return f"http://localhost:{e2e.SERVICES[name][0]}"

    env = {
        "FF_SOURCING_ADMIN_TOKEN": ADMIN_TOKEN, "FF_TRUST_ADMIN_TOKEN": ADMIN_TOKEN,
        "FF_TRACKING_NOTIFY_RELAY": "on", "FF_TRACKING_NOTIFY_BASE_URL": url("notifications"),
        "FF_TRACKING_NOTIFY_POLL_SECONDS": "1",
        "FF_SOURCING_TRUST_BASE_URL": url("trust"), "FF_LOGISTICS_GEO_URL": url("geo"),
        "FF_NOTIFICATIONS_SOURCING_BASE_URL": url("sourcing"), "FF_DEMAND_SOURCING_BASE_URL": url("sourcing"),
        "FF_RFQ_SOURCING_URL": url("sourcing"), "FF_PAYMENTS_RFQ_URL": url("rfq"),
        "FF_ASSISTANT_SOURCING_URL": url("sourcing"), "FF_ASSISTANT_LOGISTICS_URL": url("logistics"),
        "FF_ASSISTANT_TRUST_URL": url("trust"), "FF_ASSISTANT_TRACKING_URL": url("tracking"),
        "FF_ASSISTANT_RFQ_URL": url("rfq"), "FF_MEDIA_PUBLIC_BASE_URL": GW,
        "FF_GATEWAY_UPSTREAMS": json.dumps({n: url(n) for n in e2e.SERVICES if n != "gateway"}),
    }  # fmt: skip
    return env


def png_bytes(seed: int) -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes([(x * 5 + y * 11 + seed) % 256 for x in range(16) for _ in range(3)]) for y in range(16))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def seed(tmp: Path) -> dict:
    c = httpx.Client(base_url=GW, timeout=30)
    sfx = uuid.uuid4().hex[:8]
    info: dict = {"base_url": GW, "admin_token": ADMIN_TOKEN, "password": PASSWORD, "seed_errors": {}}
    users: dict[str, dict] = {}

    def h(role: str) -> dict:
        return {"Authorization": f"Bearer {users[role]['token']}"}

    def attempt(name: str, fn) -> None:
        try:
            fn()
            print(f"seed ok    {name}", flush=True)
        except Exception as e:  # noqa: BLE001
            info["seed_errors"][name] = f"{type(e).__name__}: {e}"[:300]
            print(f"seed FAIL  {name}: {info['seed_errors'][name]}", flush=True)

    def register(role: str, name: str) -> None:
        email = f"{role}{sfx}@example.com"
        d = ok(c.post("/v1/auth/register", json={"email": email, "password": PASSWORD, "name": name}), 201)
        users[role] = {"token": d["access_token"], "refresh_token": d["refresh_token"], "id": d["user"]["id"], "email": email}
        ok(c.patch("/v1/me", headers={"Authorization": f"Bearer {d['access_token']}"}, json={"role": role}))
        ok(c.patch("/v1/me", headers={"Authorization": f"Bearer {d['access_token']}"}, json={
            "company": "ACME", "default_destination": {"country_code": "IQ", "city": "Baghdad"}}))

    register("buyer", "Buyer One")
    register("supplier", "Supplier One")
    info["buyer"], info["supplier"] = users["buyer"], users["supplier"]

    found: list = []

    def search() -> None:
        found.extend(items(ok(c.get("/v1/search", params={"q": "injection molding machine"}))))
        assert found, "no search results"
        info["listing_id"] = found[0]["id"]
        info["external_supplier_id"] = found[0]["supplier"]["id"]

    attempt("search", search)
    sid = info.get("external_supplier_id")

    def claim_and_listing() -> None:
        pool = [i["supplier"] for i in found]
        claim = next((x["id"] for x in pool if x.get("trust_band") in ("green", "yellow")), sid)
        ok(c.patch("/v1/me", headers=h("supplier"), json={"supplier_id": claim}))
        ok(c.post(f"/v1/admin/supplier-claims/{users['supplier']['id']}/approve", headers={"X-Admin-Token": ADMIN_TOKEN}))
        info["claimed_supplier_id"] = claim
        body = {
            "kind": "product", "title": f"Live contract planter {sfx}", "category": "furniture", "unit": "piece", "moq": 5,
            "price": {"min": {"amount": "2.50", "currency": "USD"}, "max": {"amount": "3.00", "currency": "USD"}},
            "origin": {"country_code": "IQ", "city": "Baghdad"},
        }
        lst = ok(c.post("/v1/my/listings", json=body, headers=h("supplier")), 201)
        info["native_listing_id"] = lst["id"]
        r = c.post(f"/v1/my/listings/{lst['id']}/publish", headers=h("supplier"))
        info["native_published"] = r.status_code == 200

    attempt("verified supplier claim + native listing", claim_and_listing)

    def rfq() -> None:
        r = ok(c.post("/v1/requests", headers=h("buyer"), json={
            "kind": "product", "title": "Plastic chairs 500", "quantity": 500, "unit": "piece",
            "target_price": {"amount": "8", "currency": "USD"}, "destination": {"country_code": "IQ", "city": "Erbil"}}), 201)
        info["request_id"] = r["id"]
        o = ok(c.post(f"/v1/requests/{r['id']}/offers", headers=h("supplier"), json={
            "price": {"amount": "7.5", "currency": "USD"}, "supplier_name": "Supplier One", "moq": 100,
            "lead_time_days": 20, "incoterm": "FOB"}), 201)
        info["offer_id"] = o["id"]
        a = ok(c.post(f"/v1/offers/{o['id']}/accept", headers=h("buyer")))
        d = a.get("deal") or a
        info["deal_id"] = d.get("id") or d.get("deal_id")

    attempt("request + offer + deal", rfq)

    def convo() -> None:
        img = ok(c.post("/v1/media/images", files={"file": ("p.png", png_bytes(7), "image/png")},
                        data={"kind": "listing"}, headers=h("buyer")), 201)
        rel = "/" + img["url"].split("/", 3)[3] if img["url"].startswith("http") else img["url"]
        cv = ok(c.post("/v1/conversations", headers=h("buyer"), json={
            "participants": [{"user_id": users["supplier"]["id"], "role": "supplier"}], "my_role": "buyer",
            "context": {"type": "listing", "ref_id": info.get("listing_id", "lst_x")}}), 200, 201)
        info["conversation_id"] = cv["id"]
        ok(c.post(f"/v1/conversations/{cv['id']}/messages", headers=h("buyer"),
                  json={"type": "text", "text": "Hello, price for 500?"}), 201)
        ok(c.post(f"/v1/conversations/{cv['id']}/messages", headers=h("buyer"), json={
            "type": "attachment", "text": "see photo",
            "attachments": [{"url": rel, "kind": "image", "size": 100, "name": "p.png"}]}), 201)

    attempt("conversation + attachment message", convo)

    def watch() -> None:
        ok(c.post("/v1/watchlist", headers=h("buyer"), json={"listing_id": info["listing_id"]}), 200, 201)

    attempt("watchlist", watch)

    def shipment() -> None:
        s = ok(c.post("/v1/shipments", headers=h("buyer"), json={
            "reference": "MSKU1234565", "reference_type": "container", "label": "live contract"}), 201)
        info["shipment_id"] = s["id"]
        uid = users["buyer"]["id"]
        payload = {"shipment_id": s["id"], "owner_id": uid, "reference": "MSKU1234565", "reference_type": "container",
                   "label": "live contract", "kind": "status_changed", "status": "customs", "previous_status": "in_transit",
                   "eta": None, "delayed": False, "delay_hours": None, "event_id": None,
                   "occurred_at": datetime.now(UTC).isoformat()}
        db = sqlite3.connect(tmp / "tracking.db", timeout=10)
        try:
            db.execute("INSERT INTO tracking_outbox (dedupe_key, shipment_id, owner_id, kind, payload, created_at, attempts) "
                       "VALUES (?,?,?,?,?,?,0)", (f"live-{sfx}", s["id"], uid, "status_changed", json.dumps(payload),
                                                  datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")))
            db.commit()
        finally:
            db.close()
        deadline = time.time() + 20
        while time.time() < deadline:
            al = items(ok(c.get("/v1/alerts", headers=h("buyer"))))
            if al:
                info["alert_id"] = al[0]["id"]
                return
            time.sleep(0.5)
        raise AssertionError("shipment alert did not arrive (relay)")

    attempt("shipment + alert", shipment)

    def feed() -> None:
        p = ok(c.post("/v1/feed/posts", headers=h("supplier"), json={
            "body": f"Live contract post {sfx}: new stock of planters", "tags": ["live"]}), 201)
        info["feed_post_id"] = p["id"]

    attempt("feed post", feed)

    def freight() -> None:
        rq = ok(c.post("/v1/freight/requests", headers=h("buyer"), json={
            "origin_country": "CN", "origin_place": "Shenzhen", "destination_country": "IQ", "destination_place": "Umm Qasr",
            "cargo_description": f"Live contract ceramic tiles {sfx}", "weight_kg": "18000", "volume_cbm": "28.5",
            "mode": "sea", "container_type": "40HC", "incoterm": "FOB",
            "ready_date": time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 86400))}), 201)
        info["freight_request_id"] = rq["id"]

    attempt("freight request", freight)
    return info


def main() -> int:
    e2e.refuse_in_production()
    tmp = Path(tempfile.mkdtemp(prefix="ff-stack-"))
    procs: list = []
    stop = {"flag": False}

    def on_signal(*_: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        extra = shift_ports()
        e2e.GW = GW
        procs = e2e.start_services(tmp, extra)
        e2e.wait_health(tmp)
        print("all services healthy", flush=True)
        info = seed(tmp)
        INFO_PATH.parent.mkdir(parents=True, exist_ok=True)
        INFO_PATH.write_text(json.dumps(info, indent=2, ensure_ascii=False))
        INFO_PATH.chmod(0o600)  # holds test credentials
        print(f"info written to {INFO_PATH}", flush=True)
        print("READY", flush=True)
        while not stop["flag"]:
            dead = [p for p in procs if p.poll() is not None]
            if dead:
                print("a service exited unexpectedly", file=sys.stderr, flush=True)
                return 1
            time.sleep(1)
        return 0
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except Exception:  # noqa: BLE001
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
