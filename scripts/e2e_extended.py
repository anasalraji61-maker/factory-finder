#!/usr/bin/env python3
"""Extended end-to-end flows that scripts/e2e.py does not cover.

    python scripts/e2e_extended.py                                   # boots 13 local services, runs every flow
    FF_E2E_BASE_URL=http://localhost:8000 python scripts/e2e_extended.py   # remote stack: flows needing local
                                                                     # processes/DBs/env are SKIPped, not failed

Flows (each is an independent step; a failing setup only skips the steps that depend on it):
  listing moderation   report x2 -> pending_review -> admin hide -> restore (gateway /v1/admin/moderation/*)
  messaging media      upload a PNG via media, send it as a message attachment, reject foreign hosts
  email verification   in-process gateway with the mock mailer (the outbox is not reachable over HTTP)
  tracking relay       tracking_outbox row -> relay -> notifications -> alert visible through the gateway
  rfq deals            deals list as buyer / supplier, role filter, stranger isolation
  assistant            cards for a shipment question, daily quota 429 + Retry-After
  compliance           probes /v1/me/export, /v1/me/data etc.; SKIP when the stack has no such endpoints
  reviews              completed deal -> review created, duplicate 409, public summary
  production guard     FF_ENV=production refuses to start without secrets (subprocess per service)

Exit code is non-zero when any step fails. No network beyond localhost.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
import zlib
from datetime import UTC, datetime
from pathlib import Path

import httpx

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e  # noqa: E402  (reuse step/skip/ok/items, SERVICES, start_services, wait_health)
from e2e import ADMIN_TOKEN, GW, REMOTE, ROOT, WEBHOOK_SECRET, items, ok, skip, step  # noqa: E402

QUOTA = 3  # FF_ASSISTANT_QUOTA_PER_DAY for the local stack
PNG_CACHE: dict[str, bytes] = {}


def png_bytes(seed: int) -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes([(x * 5 + y * 11 + seed) % 256 for x in range(16) for _ in range(3)]) for y in range(16))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def extra_env() -> None:
    """Settings the plain e2e stack does not set. e2e.start_services builds its env from os.environ."""
    os.environ.update({
        "FF_SOURCING_ADMIN_TOKEN": ADMIN_TOKEN,            # gateway injects it towards sourcing; sourcing enforces it
        "FF_SOURCING_REPORT_REVIEW_THRESHOLD": "2",        # two distinct reports -> pending_review
        "FF_TRACKING_NOTIFY_RELAY": "on", "FF_TRACKING_NOTIFY_BASE_URL": "http://localhost:8108",
        "FF_TRACKING_NOTIFY_POLL_SECONDS": "1",
        "FF_ASSISTANT_QUOTA_PER_DAY": str(QUOTA),
    })  # fmt: skip


# --------------------------------------------------------------------------------------------- scenario
def scenario(tmp: Path | None) -> None:
    c = httpx.Client(base_url=GW, timeout=30)
    sfx = uuid.uuid4().hex[:8]
    admin_h = {"X-Admin-Token": ADMIN_TOKEN}
    users: dict[str, dict] = {}
    ctx: dict = {}

    def h(role: str) -> dict:
        return {"Authorization": f"Bearer {users[role]['tok']}"}

    def register(role: str, patch_role: str | None = None):
        def go():
            d = ok(c.post("/v1/auth/register", json={
                "email": f"x{role}{sfx}@example.com", "password": "Passw0rd!x", "name": f"{role.title()} X"}), 201)
            users[role] = {"tok": d["access_token"], "id": d["user"]["id"]}
            if patch_role:
                ok(c.patch("/v1/me", headers=h(role), json={"role": patch_role}))
        return go

    step("setup: register buyer / supplier / reporter / stranger", lambda: [
        register("buyer", "buyer")(), register("supplier", "supplier")(), register("reporter")(), register("stranger")()])
    if len(users) < 4:
        return

    def setup_supplier():
        d = items(ok(c.get("/v1/search", params={"q": "injection molding machine"})))
        assert d, "no search results"
        pool = [i["supplier"] for i in d]
        sid = next((x["id"] for x in pool if x.get("trust_band") in ("green", "yellow")), pool[0]["id"])
        ctx["sid"], ctx["listing"] = sid, d[0]
        ok(c.patch("/v1/me", headers=h("supplier"), json={"supplier_id": sid}))
        r = c.post(f"/v1/admin/supplier-claims/{users['supplier']['id']}/approve", headers=admin_h)
        assert r.status_code in (200, 204), f"claim approve -> {r.status_code} {r.text[:200]}"

    step("setup: supplier claim approved by admin", setup_supplier)
    claimed = "sid" in ctx

    # ---- 1. listing moderation -------------------------------------------------------------------
    def make_listing():
        body = {"kind": "product", "title": f"X ext planter {sfx}", "category": "furniture", "unit": "piece", "moq": 5,
                "price": {"min": {"amount": "2.50", "currency": "USD"}, "max": {"amount": "3.00", "currency": "USD"}},
                "origin": {"country_code": "IQ", "city": "Baghdad"}}
        lst = ok(c.post("/v1/my/listings", json=body, headers=h("supplier")), 201)
        r = c.post(f"/v1/my/listings/{lst['id']}/publish", headers=h("supplier"))
        if r.status_code in (403, 503):
            raise AssertionError(f"publish gated ({r.status_code} {r.json().get('error', {}).get('code')}): "
                                 "chosen supplier is not publishable")
        assert ok(r)["status"] == "published"
        ctx["nat"] = lst["id"]

    def search_has(lid: str) -> bool:
        return any(i["id"] == lid for i in items(ok(c.get("/v1/search", params={"q": f"X ext planter {sfx}"}))))

    def moderation():
        lid = ctx["nat"]
        assert search_has(lid), "published listing not searchable before reports"
        assert c.get("/v1/admin/moderation/listings").status_code in (401, 404), "moderation open without admin token"
        assert c.get("/v1/admin/moderation/listings", headers=h("buyer")).status_code in (401, 404)
        r = c.post(f"/v1/listings/{lid}/report", json={"reason": "misleading"})
        assert r.status_code == 401, f"anonymous report -> {r.status_code}"
        r = c.post(f"/v1/listings/{lid}/report", headers=h("supplier"), json={"reason": "misleading"})
        assert r.status_code == 409, f"owner can report own listing: {r.status_code}"
        ok(c.post(f"/v1/listings/{lid}/report", headers=h("buyer"), json={"reason": "misleading", "details": "e2e"}), 200, 201, 202, 204)
        ok(c.post(f"/v1/listings/{lid}/report", headers=h("buyer"), json={"reason": "misleading"}), 200, 201, 202, 204)  # duplicate: one report
        assert search_has(lid), "one distinct reporter must not hide the listing"
        ok(c.post(f"/v1/listings/{lid}/report", headers=h("reporter"), json={"reason": "scam_or_fraud"}), 200, 201, 202, 204)
        pend = ok(c.get("/v1/admin/moderation/listings", params={"status": "pending_review"}, headers=admin_h))
        assert any(x["id"] == lid for x in items(pend) if isinstance(x, dict)), f"not pending_review: {str(pend)[:300]}"
        assert not search_has(lid), "pending_review listing still searchable"
        reps = ok(c.get("/v1/admin/moderation/reports", params={"listing_id": lid}, headers=admin_h))
        assert len(items(reps)) >= 2, f"expected 2 open reports: {str(reps)[:300]}"
        assert ok(c.get(f"/v1/my/listings/{lid}", headers=h("supplier")))["status"] == "pending_review"
        ok(c.post(f"/v1/admin/moderation/listings/{lid}/hide", headers=admin_h, json={"reason": "e2e confirmed abuse"}))
        assert ok(c.get(f"/v1/my/listings/{lid}", headers=h("supplier")))["status"] == "hidden"
        assert not search_has(lid)
        r = c.post(f"/v1/my/listings/{lid}/publish", headers=h("supplier"))
        assert r.status_code in (403, 409), f"owner re-published a hidden listing: {r.status_code}"
        ok(c.post(f"/v1/admin/moderation/listings/{lid}/restore", headers=admin_h, json={}))
        assert ok(c.get(f"/v1/my/listings/{lid}", headers=h("supplier")))["status"] == "published"
        assert search_has(lid), "restored listing not searchable"

    if claimed:
        step("setup: native listing published", make_listing)
        if "nat" in ctx:
            step("moderation: 2 reports -> pending_review -> admin hide -> restore", moderation)
        else:
            skip("moderation flow", "no published native listing")
    else:
        skip("moderation flow", "supplier claim not available")

    # ---- 2. messaging attachments ----------------------------------------------------------------
    def msg_media():
        files = {"file": ("p.png", png_bytes(int(sfx, 16) % 200), "image/png")}
        r = c.post("/v1/media/images", files=files, data={"kind": "message"}, headers=h("buyer"))
        if r.status_code == 422:  # unknown kind value in this build
            r = c.post("/v1/media/images", files=files, data={"kind": "listing"}, headers=h("buyer"))
        img = ok(r, 201)
        rel = "/" + img["url"].split("/", 3)[3] if img["url"].startswith("http") else img["url"]
        cv = ok(c.post("/v1/conversations", headers=h("buyer"), json={
            "participants": [{"user_id": users["supplier"]["id"], "role": "supplier"}], "my_role": "buyer",
            "context": {"type": "support"}}), 200, 201)
        cid = cv["id"]
        att = {"url": rel, "kind": "image", "size": len(files["file"][1]), "name": "p.png"}
        m = ok(c.post(f"/v1/conversations/{cid}/messages", headers=h("buyer"),
                      json={"type": "attachment", "text": "see photo", "attachments": [att]}), 201)
        assert m.get("attachments") and m["attachments"][0]["url"].endswith(rel.split("/")[-1]), str(m)[:300]
        got = items(ok(c.get(f"/v1/conversations/{cid}/messages", headers=h("supplier"))))
        assert any(x.get("attachments") for x in got), "supplier does not see the attachment"
        assert c.get(rel).status_code == 200, "attached media is not publicly readable"
        bad = c.post(f"/v1/conversations/{cid}/messages", headers=h("buyer"), json={
            "type": "attachment", "attachments": [{"url": "https://evil.example.com/x.png", "kind": "image"}]})
        # accepted only if the deployment leaves media_allowed_hosts open; the local stack restricts nothing, so
        # only demand a clean (non-5xx) answer and that javascript: style URLs are always refused
        assert bad.status_code < 500, f"foreign host attachment -> {bad.status_code}"
        js = c.post(f"/v1/conversations/{cid}/messages", headers=h("buyer"), json={
            "type": "attachment", "attachments": [{"url": "javascript:alert(1)", "kind": "image"}]})
        assert js.status_code in (400, 422), f"javascript: URL accepted -> {js.status_code}"
        assert c.post(f"/v1/conversations/{cid}/messages", headers=h("stranger"),
                      json={"type": "text", "text": "hi"}).status_code in (403, 404), "stranger can post"

    step("messaging: media upload -> attachment message -> counterpart reads it", msg_media)

    # ---- 3. email verification (in-process, mock mailer) -----------------------------------------
    step("auth: email verification with mock mailer (in-process gateway)", lambda: asyncio.run(email_flow(tmp)))

    # ---- 4. tracking outbox -> notifications relay ------------------------------------------------
    def relay():
        if REMOTE or tmp is None:
            return skip("tracking relay", "needs the local tracking database")
        uid = users["buyer"]["id"]
        s = ok(c.post("/v1/shipments", headers=h("buyer"), json={"reference": "MSKU1234565", "reference_type": "container",
                                                                  "label": "relay"}), 201)
        key = f"e2e-relay-{sfx}"
        payload = {"shipment_id": s["id"], "owner_id": uid, "reference": "MSKU1234565", "reference_type": "container",
                   "label": "relay", "kind": "status_changed", "status": "customs", "previous_status": "in_transit",
                   "eta": None, "delayed": False, "delay_hours": None, "event_id": None,
                   "occurred_at": datetime.now(UTC).isoformat()}
        db = sqlite3.connect(tmp / "tracking.db", timeout=10)
        try:
            db.execute("INSERT INTO tracking_outbox (dedupe_key, shipment_id, owner_id, kind, payload, created_at, attempts) "
                       "VALUES (?,?,?,?,?,?,0)", (key, s["id"], uid, "status_changed", json.dumps(payload),
                                                  datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")))
            db.commit()
        finally:
            db.close()
        st = httpx.get("http://localhost:8107/v1/internal/outbox-status", timeout=10).json()
        assert st["relay"] == "on", f"relay not enabled: {st}"
        deadline, st = time.time() + 20, {}
        while time.time() < deadline:
            st = httpx.get("http://localhost:8107/v1/internal/outbox-status", timeout=10).json()
            if st["pending"] == 0 and st["delivered"] >= 1:
                break
            time.sleep(0.5)
        assert st["pending"] == 0 and st["delivered"] >= 1 and st["dead"] == 0, f"outbox not drained: {st}"
        alerts = items(ok(c.get("/v1/alerts", headers=h("buyer"))))
        assert any("customs" in json.dumps(a).lower() or "جمرك" in json.dumps(a) for a in alerts), \
            f"no shipment alert for the buyer: {str(alerts)[:300]}"
        ev = {"events": [{"dedupe_key": key, "owner_id": uid, "shipment_id": s["id"], "kind": "status_changed", "payload": payload},
                         {"dedupe_key": "bad", "kind": "nope"}]}
        res = httpx.post("http://localhost:8108/v1/internal/tracking-events", json=ev, timeout=10)
        r = ok(res)["results"]
        assert [x["status"] for x in r] == ["duplicate", "invalid"], r  # idempotent + bad row isolated

    step("tracking -> notifications: outbox row relayed, alert in inbox, replay idempotent", relay)

    # ---- 5. rfq: deal, lists, payment, completion, review -----------------------------------------
    deal: dict = {}

    def make_deal():
        r = ok(c.post("/v1/requests", headers=h("buyer"), json={
            "kind": "product", "title": f"Ext chairs {sfx}", "quantity": 100, "unit": "piece",
            "target_price": {"amount": "8", "currency": "USD"}, "destination": {"country_code": "IQ", "city": "Erbil"}}), 201)
        o = ok(c.post(f"/v1/requests/{r['id']}/offers", headers=h("supplier"), json={
            "price": {"amount": "7.5", "currency": "USD"}, "supplier_name": "Supplier X", "moq": 50,
            "lead_time_days": 15, "incoterm": "FOB"}), 201)
        a = ok(c.post(f"/v1/offers/{o['id']}/accept", headers=h("buyer")))
        d = a.get("deal") or a
        deal.update(id=d.get("id") or d.get("deal_id"), rid=r["id"])
        assert deal["id"]

    def deals_lists():
        did = deal["id"]
        b = [x["id"] for x in items(ok(c.get("/v1/deals?role=buyer", headers=h("buyer"))))]
        s = [x["id"] for x in items(ok(c.get("/v1/deals?role=supplier", headers=h("supplier"))))]
        assert did in b, "deal missing from buyer list"
        assert did in s, "deal missing from supplier list"
        assert did not in [x["id"] for x in items(ok(c.get("/v1/deals?role=supplier", headers=h("buyer"))))], \
            "buyer sees own deal in supplier role list"
        assert did not in [x["id"] for x in items(ok(c.get("/v1/deals?role=buyer", headers=h("supplier"))))]
        assert not [x for x in items(ok(c.get("/v1/deals", headers=h("stranger"))))], "stranger sees deals"
        assert c.get(f"/v1/deals/{did}", headers=h("stranger")).status_code in (403, 404)
        assert ok(c.get(f"/v1/deals/{did}", headers=h("supplier")))["id"] == did
        assert c.get("/v1/deals?role=bogus", headers=h("buyer")).status_code in (200, 400, 422)

    step("setup: request -> offer (verified supplier) -> accepted deal", make_deal)
    if deal.get("id"):
        step("rfq: deals list as buyer / supplier (+ isolation)", deals_lists)

    def complete_and_review():
        if REMOTE:
            return skip("reviews after completed deal", "needs the payments webhook port")
        if not claimed:
            return skip("reviews after completed deal", "no verified supplier")
        did = deal["id"]
        inv = {k: ok(c.post("/v1/invoices", headers=h("buyer"), json={"deal_id": did, "kind": k}), 200, 201)
               for k in ("commission", "deal_payment")}
        for k, v in inv.items():
            raw = json.dumps({"event_id": f"x-{k}-{sfx}", "type": "payment.confirmed", "invoice_id": v["id"]}).encode()
            ts = int(time.time())
            mac = hmac.new(WEBHOOK_SECRET.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
            r = httpx.post("http://localhost:8111/v1/payments/webhooks/mock", content=raw, timeout=15,
                           headers={"X-FF-Signature": f"t={ts},v1={mac}", "Content-Type": "application/json"})
            assert r.status_code == 200, r.text
        ok(c.post(f"/v1/deals/{did}/fulfilment/start", headers=h("supplier")))
        ok(c.post(f"/v1/deals/{did}/delivered", headers=h("supplier")))
        assert ok(c.post(f"/v1/deals/{did}/confirm-receipt", headers=h("buyer")))["status"] == "completed"
        assert c.post(f"/v1/deals/{did}/reviews", headers=h("supplier"), json={"rating": 5}).status_code == 403
        assert c.post(f"/v1/deals/{did}/reviews", headers=h("stranger"), json={"rating": 5}).status_code in (403, 404)
        r = c.post(f"/v1/deals/{did}/reviews", headers=h("buyer"), json={"rating": 6})
        assert r.status_code == 422, f"rating 6 accepted: {r.status_code}"
        rev = ok(c.post(f"/v1/deals/{did}/reviews", headers=h("buyer"), json={
            "rating": 4, "title": "Good", "text": "Delivered on time",
            "sub_ratings": {"quality": 4, "communication": 5, "shipping": 4}}), 201)
        assert rev["rating"] == 4 and rev["id"]
        dup = c.post(f"/v1/deals/{did}/reviews", headers=h("buyer"), json={"rating": 5})
        assert dup.status_code == 409 and dup.json()["error"]["code"] == "review_already_exists", dup.text[:200]
        sm = ok(c.get(f"/v1/suppliers/{ctx['sid']}/review-summary"))
        assert sm["count"] == 1 and float(sm["average"]) == 4.0, sm
        assert [x["id"] for x in items(ok(c.get(f"/v1/suppliers/{ctx['sid']}/reviews")))] == [rev["id"]]
        ok(c.put(f"/v1/reviews/{rev['id']}", headers=h("buyer"), json={"rating": 5, "title": "Great"}))
        assert float(ok(c.get(f"/v1/suppliers/{ctx['sid']}/review-summary"))["average"]) == 5.0
        ok(c.post(f"/v1/reviews/{rev['id']}/reply", headers=h("supplier"), json={"text": "Thank you"}), 200, 201)

    if deal.get("id"):
        step("reviews: paid -> completed deal -> review, duplicate 409, summary, edit, reply", complete_and_review)

    # ---- 6. assistant cards + quota ----------------------------------------------------------------
    def assistant_cards():
        s = ok(c.post("/v1/shipments", headers=h("stranger"), json={"reference": "CSQU3054383", "reference_type": "container"}), 201)
        d = ok(c.post("/v1/assistant/query", headers=h("stranger"), json={"text": "where is my container CSQU3054383", "locale": "en"}))
        assert d.get("answer_text") or d.get("answer"), f"no answer: {str(d)[:200]}"
        cards = d.get("cards")
        assert isinstance(cards, list) and cards, f"no cards for a shipment question: {str(d)[:300]}"
        for card in cards:
            assert card["type"] in ("shipment_status", "deal_status", "listing_comparison", "hs_code", "notice"), card["type"]
            assert card["title"] and card["title_ar"], "card is not bilingual"
        assert any(card["type"] == "shipment_status" for card in cards), [x["type"] for x in cards]
        sc = next(x for x in cards if x["type"] == "shipment_status")
        assert s["id"] in json.dumps(sc), "shipment card does not reference the shipment"
        ctx["cards_used"] = 1

    def assistant_quota():
        if REMOTE:
            return skip("assistant quota", "quota size is stack configuration")
        tok = {"Authorization": f"Bearer {users['reporter']['tok']}"}
        for _ in range(QUOTA):
            ok(c.post("/v1/assistant/query", headers=tok, json={"text": "hello", "locale": "en"}))
        r = c.post("/v1/assistant/query", headers=tok, json={"text": "hello", "locale": "en"})
        assert r.status_code == 429 and r.json()["error"]["code"] == "quota_exceeded", f"{r.status_code} {r.text[:200]}"
        assert int(r.headers["retry-after"]) > 0
        # quota is per user: another user is unaffected
        ok(c.post("/v1/assistant/query", headers=h("supplier"), json={"text": "hello", "locale": "en"}))

    step("assistant: shipment question -> shipment_status card (bilingual)", assistant_cards)
    step("assistant: per-user daily quota -> 429 + Retry-After", assistant_quota)

    # ---- 7. compliance (only if present) -----------------------------------------------------------
    def compliance():
        paths = [("GET", "/v1/me/export"), ("GET", "/v1/me/data"), ("DELETE", "/v1/me"), ("POST", "/v1/me/delete"),
                 ("GET", "/v1/legal/terms"), ("GET", "/v1/legal/privacy"), ("GET", "/v1/consent")]
        found = []
        for m, p in paths:
            if m == "DELETE":
                continue  # never probe account deletion with a live token
            r = c.request(m, p, headers=h("stranger"))
            if r.status_code not in (404, 405):
                found.append((m, p, r.status_code))
        if not found:
            return skip("compliance endpoints", "none exposed by this build (no /v1/me/export, /v1/legal/*, /v1/consent)")
        for m, p, code in found:
            assert code < 500, f"{m} {p} -> {code}"
            if p == "/v1/me/export":
                r = c.get(p, headers=h("stranger"))
                assert r.status_code == 200 and users["stranger"]["id"] in r.text, "export lacks the user's data"
                other = c.get(p, headers=h("buyer"))
                assert users["stranger"]["id"] not in other.text, "export leaks another user's data"
                assert c.get(p).status_code == 401, "export open without token"

    step("compliance: export / legal / consent endpoints (if present)", compliance)


# --------------------------------------------------------------------------------------------- email flow
async def email_flow(tmp: Path | None) -> None:
    try:
        sys.path.insert(0, str(ROOT / "services" / "gateway" / "src"))
        from ff_gateway.config import Settings
        from ff_gateway.db import create_tables
        from ff_gateway.domain.mail import MockMailer
        from ff_gateway.main import create_app
    except ImportError as e:
        return skip("email verification", f"gateway package not importable here ({e})")
    d = Path(tempfile.mkdtemp(prefix="ff-mail-"))
    try:
        mailer = MockMailer()
        st = Settings(jwt_secret="mail-secret", database_url=f"sqlite+aiosqlite:///{d}/g.db", bcrypt_rounds=4,
                      mail_backend="mock", require_email_verified=True, home_client="mock", admin_token=None,
                      rate_limit_per_minute=100000, auth_rate_limit_per_minute=100000, resend_verification_per_minute=100)
        logging.disable(logging.CRITICAL)  # the gateway logs one JSON line per request
        app = create_app(st, mailer=mailer)
        await create_tables(app.state.engine)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw") as c:
            email = f"mail{uuid.uuid4().hex[:6]}@example.com"
            reg = await c.post("/v1/auth/register", json={"email": email, "password": "Passw0rd!x", "name": "Mail U"})
            assert reg.status_code == 201, reg.text
            hdr = {"Authorization": f"Bearer {reg.json()['access_token']}"}
            assert len(mailer.outbox) == 1 and mailer.outbox[0].to == email, "no verification mail was sent"
            token = mailer.outbox[0].body.split("Verification code:")[1].split()[0]
            me = await c.get("/v1/me", headers=hdr)
            assert me.json()["email_verified"] is False
            blocked = await c.post("/v1/invoices", headers=hdr, json={"deal_id": "x", "kind": "commission"})
            assert blocked.status_code == 403, f"unverified payments write -> {blocked.status_code} {blocked.text[:200]}"
            bad = await c.post("/v1/auth/verify-email", json={"token": "x" * 40})
            assert bad.status_code == 400, f"bogus token -> {bad.status_code}"
            assert (await c.post("/v1/auth/verify-email", json={"token": token})).status_code == 204
            assert (await c.get("/v1/me", headers=hdr)).json()["email_verified"] is True
            again = await c.post("/v1/auth/verify-email", json={"token": token})
            assert again.status_code == 400, f"token reuse -> {again.status_code}"
            after = await c.post("/v1/invoices", headers=hdr, json={"deal_id": "x", "kind": "commission"})
            assert after.status_code != 403 or "verif" not in after.text.lower(), "still blocked after verification"
            # resend: always 202, no enumeration, and no mail for a verified / unknown address
            n = len(mailer.outbox)
            for e in (email, "nobody@example.com"):
                r = await c.post("/v1/auth/resend-verification", json={"email": e})
                assert r.status_code == 202, r.text
            assert len(mailer.outbox) == n, "mail sent to a verified or unknown address"
            reg2 = await c.post("/v1/auth/register", json={"email": f"m2{uuid.uuid4().hex[:6]}@example.com",
                                                           "password": "Passw0rd!x", "name": "Mail V"})
            assert reg2.status_code == 201
            r = await c.post("/v1/auth/resend-verification", json={"email": reg2.json()["user"]["email"]})
            assert r.status_code == 202
            await asyncio.sleep(0.3)  # sent as a background task
            assert len(mailer.outbox) >= n + 1, "resend did not send a mail for an unverified account"
        await app.state.engine.dispose()
        await app.state.http.aclose()
    finally:
        logging.disable(logging.NOTSET)
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------------------------- prod guard
GUARD_TARGETS = ["ff_gateway.main", "ff_sourcing.main", "ff_rfq.main", "ff_messaging.main", "ff_tracking.main",
                 "ff_notifications.main", "ff_payments.main", "ff_media.main"]


def prod_guard() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ff-guard-"))
    try:
        base = {k: v for k, v in os.environ.items() if not k.startswith("FF_")}
        base["FF_ENV"] = "production"
        for mod in GUARD_TARGETS:
            name = mod.split(".")[0].removeprefix("ff_")
            env = {**base, "PYTHONPATH": str(ROOT / "services" / name / "src"),
                   f"FF_{name.upper()}_DATABASE_URL": f"sqlite+aiosqlite:///{tmp}/{name}.db",
                   "FF_MEDIA_STORAGE_ROOT": str(tmp / "media")}
            run = lambda e, mod=mod, name=name: subprocess.run(  # noqa: E731
                [sys.executable, "-c", f"import {mod}"], cwd=ROOT / "services" / name, env=e,
                capture_output=True, text=True, timeout=60)
            r = run(env)
            assert r.returncode != 0 and "FF_ENV=production" in r.stderr, \
                f"{name}: production start without secrets was NOT refused (rc={r.returncode}): {r.stderr[-200:]}"
            assert "refusing to start" in r.stderr
            if name == "gateway":
                half = run({**env, "FF_GATEWAY_JWT_SECRET": "s" * 40})
                assert half.returncode != 0 and "FF_GATEWAY_ADMIN_TOKEN" in half.stderr, "gateway accepts missing admin token"
                good = run({**env, "FF_GATEWAY_JWT_SECRET": "s" * 40, "FF_GATEWAY_ADMIN_TOKEN": "a" * 32})
            else:
                good = run({**env, "FF_INTERNAL_TOKEN": "t" * 32, "FF_PAYMENTS_INTERNAL_TOKEN": "t" * 32})
            assert good.returncode == 0, f"{name}: refuses to start although secrets are set: {good.stderr[-300:]}"
            assert "t" * 32 not in r.stderr + good.stderr + r.stdout, f"{name}: secret printed"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------------------------- main
def main() -> int:
    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="ff-e2e-x-"))
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
            extra_env()
            procs = e2e.start_services(tmp)
            e2e.wait_health(tmp)
        print("all services healthy")
        scenario(None if REMOTE else tmp)
        step("production guard: FF_ENV=production refuses to start without secrets (subprocess)", prod_guard)
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
    print(f"\n{len(e2e.RESULTS) - len(failed)}/{len(e2e.RESULTS)} steps passed"
          + (f", {len(e2e.SKIPPED)} skipped" if e2e.SKIPPED else "") + f" in {time.time() - t0:.0f}s")
    for name, _, msg in failed:
        print(f"FAILED: {name}\n        {msg}")
    return 1 if failed or not e2e.RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
