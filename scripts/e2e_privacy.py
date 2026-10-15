#!/usr/bin/env python3
"""Cross-service privacy e2e: account export (GET /v1/me/export) and erasure (DELETE /v1/me).

    python scripts/e2e_privacy.py     # boots the 15 local services (mock adapters, no network), runs the privacy flow

A victim user gets data in rfq, messaging, feed, media, tracking, notifications, payments and trust; a bystander
gets data too. Checks: the export holds every service's data and no secrets or other users' PII; after DELETE /v1/me
the deletion jobs are done, tokens are revoked, per-service data is erased/anonymized, legal-hold records (payments,
rfq deals) stay but carry no free text, and the bystander's data is unchanged. Per-service checks call the
internal routes on the local ports (no FF_INTERNAL_TOKEN in the e2e stack), so they are skipped for a remote stack.
Exit code is non-zero when any step fails.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
import zlib
from pathlib import Path

import httpx

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e  # noqa: E402
from e2e import ADMIN_TOKEN, GW, REMOTE, SERVICES, items, ok, skip, step  # noqa: E402

PW = "Passw0rd!x"


def png(seed: int) -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes([(x * 7 + y * 3 + seed) % 256 for x in range(16) for _ in range(3)]) for y in range(16))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def internal(service: str, uid: str) -> dict:
    """Direct call to a service's internal export route (local stack only)."""
    r = httpx.post(f"http://localhost:{SERVICES[service][0]}/v1/internal/users/{uid}/export", timeout=30)
    assert r.status_code == 200, f"{service} export {r.status_code}"
    return r.json()


def flow() -> None:
    c = httpx.Client(base_url=GW, timeout=30)
    sfx = uuid.uuid4().hex[:8]
    admin_h = {"X-Admin-Token": ADMIN_TOKEN}
    U: dict[str, dict] = {}
    memo = f"VICTIM-MEMO-{sfx}"
    secret_texts = {"req": f"victim request text {sfx}", "req2": f"victim open request {sfx}", "msg": f"victim message {sfx}", "post": f"victim post {sfx} planters",
                    "comment": f"victim comment {sfx}", "note": f"victim offer note {sfx}", "report": f"victim trust report {sfx}"}

    def h(who: str) -> dict:
        return {"Authorization": f"Bearer {U[who]['tok']}"}

    def register(who: str, role: str):
        d = ok(c.post("/v1/auth/register", json={"email": f"{who}{sfx}@example.com", "password": PW, "name": who.title()}), 201)
        U[who] = {"tok": d["access_token"], "ref": d["refresh_token"], "id": d["user"]["id"], "email": f"{who}{sfx}@example.com"}
        ok(c.patch("/v1/me", headers=h(who), json={"role": role, "company": f"{who} Co"}))

    def setup():
        register("victim", "supplier")
        register("bystander", "buyer")
        register("partner", "supplier")
        # victim becomes a verified supplier (feed needs it)
        r = ok(c.get("/v1/search", params={"q": "injection molding machine"}))
        sid = items(r)[0]["supplier"]["id"]
        U["victim"]["supplier_id"] = sid
        ok(c.patch("/v1/me", headers=h("victim"), json={"supplier_id": sid}))
        ok(c.post(f"/v1/admin/supplier-claims/{U['victim']['id']}/approve", headers=admin_h))
        U["listing"] = items(r)[0]["id"]

    step("setup: victim (verified supplier), bystander, partner", setup)
    if len(U) < 4:
        return

    S: dict = {}  # ids created

    def make_data(who: str, tag: str):
        t = secret_texts if who == "victim" else {k: v.replace("victim", who) for k, v in secret_texts.items()}
        out: dict = {}
        # rfq: the victim is the buyer of a request answered by partner; accepted -> deal
        r = ok(c.post("/v1/requests", headers=h(who), json={
            "kind": "product", "title": t["req"], "quantity": 100, "unit": "piece",
            "target_price": {"amount": "8", "currency": "USD"}, "destination": {"country_code": "IQ", "city": "Baghdad"}}), 201)
        o = ok(c.post(f"/v1/requests/{r['id']}/offers", headers=h("partner"), json={
            "price": {"amount": "7.5", "currency": "USD"}, "supplier_name": "Partner", "moq": 100, "lead_time_days": 20,
            "incoterm": "FOB", "notes": f"partner offer to {who} {sfx}"}), 201)
        a = ok(c.post(f"/v1/offers/{o['id']}/accept", headers=h(who)))
        out["deal"] = (a.get("deal") or a)["id"]
        out["request"] = r["id"]
        # victim also makes an offer on a bystander-independent request of the partner (offer note = free text)
        if who == "victim":
            r2 = ok(c.post("/v1/requests", headers=h("partner"), json={
                "kind": "product", "title": f"partner wants chairs {sfx}", "quantity": 10, "unit": "piece",
                "target_price": {"amount": "8", "currency": "USD"}, "destination": {"country_code": "IQ", "city": "Baghdad"}}), 201)
            ok(c.post(f"/v1/requests/{r2['id']}/offers", headers=h(who), json={
                "price": {"amount": "7", "currency": "USD"}, "supplier_name": "Victim Co", "moq": 10, "lead_time_days": 10,
                "incoterm": "FOB", "notes": t["note"]}), 201)
            out["partner_request"] = r2["id"]
            ok(c.post("/v1/requests", headers=h(who), json={
                "kind": "product", "title": t["req2"], "quantity": 5, "unit": "piece",
                "target_price": {"amount": "8", "currency": "USD"}, "destination": {"country_code": "IQ", "city": "Baghdad"}}), 201)
        # payments
        inv = ok(c.post("/v1/invoices", headers=h(who), json={"deal_id": out["deal"], "kind": "commission", "memo": memo if who == "victim" else f"BYSTANDER-MEMO-{sfx}"}), 200, 201)
        out["invoice"] = inv["id"]
        # messaging
        cv = ok(c.post("/v1/conversations", headers=h(who), json={
            "participants": [{"user_id": U["partner"]["id"], "role": "supplier"}], "my_role": "buyer",
            "context": {"type": "listing", "ref_id": U["listing"]}}), 200, 201)
        ok(c.post(f"/v1/conversations/{cv['id']}/messages", headers=h(who), json={"type": "text", "text": t["msg"]}), 201)
        out["conv"] = cv["id"]
        # tracking
        ref = "CSQU3054383" if who == "victim" else "MSKU1234565"
        out["shipment"] = ok(c.post("/v1/shipments", headers=h(who), json={"reference": ref, "reference_type": "container", "label": f"{who} cargo {sfx}"}), 201)["id"]
        # notifications
        out["watch"] = ok(c.post("/v1/watchlist", headers=h(who), json={"listing_id": U["listing"]}), 200, 201)["id"]
        out["device"] = ok(c.post("/v1/devices", headers=h(who), json={"platform": "android", "token": f"fcm-{who}-{sfx}-{'x' * 40}"}), 200, 201)["id"]
        # media
        files = {"file": ("p.png", png(int(sfx, 16) % 200 + (0 if who == "victim" else 11)), "image/png")}
        out["image"] = ok(c.post("/v1/media/images", files=files, data={"kind": "listing"}, headers=h(who)), 201)["id"]
        # trust claim/report against the supplier (rate limit 5/h)
        r = c.post(f"/v1/trust/suppliers/{U['victim']['supplier_id']}/report", headers=h(who), json={"type": "quality", "text": t["report"]})
        out["trust_report"] = ok(r, 201)["id"] if r.status_code == 201 else None
        # feed: like + comment on a partner... the victim also authors a post
        if who == "victim":
            p = ok(c.post("/v1/feed/posts", headers=h(who), json={"body": t["post"], "tags": ["privacy"]}), 201)
            out["post"] = p["id"]
            ok(c.post(f"/v1/feed/suppliers/{U['victim']['supplier_id']}/follow", headers=h("bystander")))
            ok(c.put(f"/v1/feed/posts/{p['id']}/like", headers=h("bystander")))
            ok(c.post(f"/v1/feed/posts/{p['id']}/comments", headers=h("bystander"), json={"body": f"bystander comment {sfx}"}), 201)
            ok(c.post(f"/v1/feed/posts/{p['id']}/comments", headers=h("partner"), json={"body": f"partner comment {sfx}"}), 201)
        S[who] = out

    step("data: victim has data in rfq/messaging/media/tracking/notifications/payments/trust/feed", lambda: make_data("victim", "v"))
    step("data: bystander has data in the same services", lambda: make_data("bystander", "b"))
    if "victim" not in S or "bystander" not in S:
        return

    def victim_comments_elsewhere():
        r = c.post(f"/v1/feed/posts/{S['victim']['post']}/comments", headers=h("victim"), json={"body": secret_texts["comment"]})
        ok(r, 201)
        ok(c.put(f"/v1/feed/posts/{S['victim']['post']}/like", headers=h("victim")))

    step("data: victim comment + like (feed)", victim_comments_elsewhere)

    def export_of(who: str) -> tuple[dict, str]:
        r = c.get("/v1/me/export", headers=h(who))
        d = ok(r)
        return d, r.text

    bystander_before: dict = {}

    def export_all():
        d, raw = export_of("victim")
        S["export"] = d
        print("   export services:", {k: (v["status"], sorted((v.get("data") or {}).keys())) for k, v in d["services"].items()})
        assert d["format_version"] == 1 and d["partial"] is False, {k: v for k, v in d["services"].items() if v["status"] != "ok"}
        assert d["user"]["id"] == U["victim"]["id"] and d["user"]["email"] == U["victim"]["email"]
        for svc in ("notifications", "messaging", "feed", "rfq", "media", "trust", "payments", "tracking"):
            sv = d["services"].get(svc)
            assert sv and sv["status"] == "ok" and sv.get("data"), f"{svc} missing/empty in export: {str(sv)[:200]}"
        for key, label in (("req", "rfq request"), ("msg", "message"), ("post", "feed post"), ("comment", "feed comment"),
                           ("note", "rfq offer note"), ("report", "trust report")):
            assert secret_texts[key] in raw, f"{label} text missing from export"
        assert memo in raw, "payments invoice memo missing from export"
        for needle, label in ((S["victim"]["shipment"], "tracking shipment"), (S["victim"]["watch"], "watch"), (S["victim"]["device"], "device"),
                              (S["victim"]["image"], "media image"), (S["victim"]["invoice"], "invoice"), (S["victim"]["deal"], "deal"),
                              (S["victim"]["conv"], "conversation")):
            assert needle in raw, f"{label} id missing from export"
        # no secrets / hashes / other users' PII
        low = raw.lower()
        for bad in ("$2b$", "$2a$", "password_hash", "hashed_password", U["victim"]["ref"], U["victim"]["tok"], f"fcm-victim-{sfx}-{'x' * 40}"):
            assert bad.lower() not in low, f"secret-looking value in export: {bad[:20]}"
        for who in ("bystander", "partner"):
            assert U[who]["email"] not in raw, f"{who} email leaked into the victim export"
        assert f"BYSTANDER-MEMO-{sfx}" not in raw and f"bystander request text {sfx}" not in raw and f"bystander message {sfx}" not in raw
        assert S["bystander"]["invoice"] not in raw and S["bystander"]["shipment"] not in raw and S["bystander"]["watch"] not in raw
        b, _ = export_of("bystander")
        bystander_before.update(b)

    step("export: every service present, own data complete, no secrets/hashes/other users' data", export_all)
    if "export" not in S:
        return

    def export_guards():
        assert c.get("/v1/me/export").status_code == 401
        r = c.get("/v1/internal/users/x/export")
        assert r.status_code in (401, 404), f"internal route reachable via the gateway: {r.status_code}"

    step("export: needs a token; internal routes not reachable through the gateway", export_guards)

    pre_local: dict = {}

    def pre_state():
        if REMOTE:
            return skip("per-service pre-state", "remote stack")
        for svc in ("notifications", "messaging", "feed", "rfq", "media", "trust", "payments", "tracking"):
            pre_local[svc] = internal(svc, U["victim"]["id"])
            assert json.dumps(pre_local[svc]), svc

    step("per-service export (direct) has data before deletion", pre_state)

    def delete_guards():
        assert c.request("DELETE", "/v1/me", json={"password": PW}).status_code == 401
        r = c.request("DELETE", "/v1/me", headers=h("victim"), json={"password": "wrong-password"})
        assert r.status_code in (401, 403), r.status_code
        assert ok(c.get("/v1/me", headers=h("victim")))["id"] == U["victim"]["id"], "wrong password must not delete"

    step("delete: needs auth and the right password", delete_guards)

    def delete():
        r = c.request("DELETE", "/v1/me", headers=h("victim"), json={"password": PW})
        d = ok(r, 200, 202)
        S["deletion"] = d
        assert d["status"] == "deleted" and r.status_code == 200, f"deletion not complete: {d}"
        assert d["services"] and all(v == "done" for v in d["services"].values()), d["services"]
        assert {"rfq", "messaging", "feed", "media", "tracking", "notifications", "payments", "trust"} <= set(d["services"]), d["services"]

    step("delete: DELETE /v1/me completes every service job", delete)
    if "deletion" not in S:
        return

    def jobs():
        r = c.get("/v1/admin/account-deletions", headers=admin_h, params={"status": "pending"})
        if r.status_code == 404:
            return skip("admin deletion jobs", "admin token not configured")
        pend = [i for i in ok(r)["items"] if i["user_id"] == U["victim"]["id"]]
        assert not pend, pend
        dead = [i for i in ok(c.get("/v1/admin/account-deletions", headers=admin_h, params={"status": "dead"}))["items"] if i["user_id"] == U["victim"]["id"]]
        assert not dead, dead

    step("delete: no pending/dead deletion jobs for the user", jobs)

    def again_idempotent():
        r = c.request("DELETE", "/v1/me", headers=h("victim"), json={"password": PW})
        assert r.status_code in (200, 401, 403, 429), r.status_code  # token revoked / rate limited are fine too

    step("delete: repeating is safe", again_idempotent)

    def tokens_revoked():
        assert c.get("/v1/me", headers=h("victim")).status_code in (401, 403), "access token still works"
        assert c.get("/v1/me/export", headers=h("victim")).status_code in (401, 403)
        r = c.post("/v1/auth/refresh", json={"refresh_token": U["victim"]["ref"]})
        assert r.status_code in (401, 403, 422), f"refresh token still works: {r.status_code}"
        r = c.post("/v1/auth/login", json={"email": U["victim"]["email"], "password": PW})
        assert r.status_code in (401, 403), f"deleted account can log in: {r.status_code}"
        assert c.get("/v1/shipments", headers=h("victim")).status_code in (401, 403)

    step("delete: access/refresh tokens revoked, login impossible", tokens_revoked)

    def erased():
        if REMOTE:
            return skip("per-service erasure checks", "remote stack")
        uid = U["victim"]["id"]
        raw = {svc: json.dumps(internal(svc, uid)) for svc in pre_local}
        for svc, txt in raw.items():
            assert U["victim"]["email"] not in txt, f"{svc}: email still stored"
        # fully erased
        for svc, needles in (("tracking", [S["victim"]["shipment"]]), ("notifications", [S["victim"]["watch"], S["victim"]["device"]]),
                             ("media", [S["victim"]["image"]])):
            for n in needles:
                assert n not in raw[svc], f"{svc}: {n} survived erasure"
        # anonymized free text
        assert secret_texts["post"] not in raw["feed"] and secret_texts["comment"] not in raw["feed"], "feed content survived"
        assert secret_texts["req2"] not in raw["rfq"] and secret_texts["note"] not in raw["rfq"], "rfq free text survived"
        assert secret_texts["msg"] not in raw["messaging"], "messaging export still returns the user's messages"
        # legal hold: invoice and deal retained, memo gone
        assert S["victim"]["invoice"] in raw["payments"], "invoice must be retained (legal hold)"
        assert memo not in raw["payments"], "invoice memo not anonymized"
        assert S["victim"]["deal"] in raw["rfq"], "deal must be retained (legal hold)"
        assert secret_texts["post"] not in raw["trust"]

    step("erase: per-service data erased/anonymized, ledger + deals retained without free text", erased)

    def public_surfaces():
        # the victim's post is gone from public feed; counterparties no longer see message text as the victim
        assert not any(i["id"] == S["victim"]["post"] for i in items(ok(c.get("/v1/feed/trending")))), "deleted post still trending"
        cv = ok(c.get(f"/v1/conversations/{S['victim']['conv']}/messages", headers=h("partner")))
        txt = json.dumps(cv)
        assert U["victim"]["id"] not in txt, "victim id still on counterparty's thread"
        assert U["victim"]["email"] not in txt

    step("erase: public feed + counterparty thread no longer expose the victim", public_surfaces)

    def bystander_untouched():
        b, raw = export_of("bystander")
        assert b["partial"] is False
        for svc, v in bystander_before["services"].items():
            if svc in ("feed", "messaging"):
                continue  # shared surfaces legitimately change (victim's post/messages are gone)
            before = json.dumps(v.get("data"), sort_keys=True, default=str)
            after = json.dumps(b["services"][svc].get("data"), sort_keys=True, default=str)
            assert before == after, f"bystander {svc} export changed after another user's deletion"
        for k in ("invoice", "shipment", "watch", "device", "image", "deal", "request"):
            assert S["bystander"][k] in raw, f"bystander {k} lost"
        assert f"BYSTANDER-MEMO-{sfx}" in raw and f"bystander request text {sfx}" in raw and f"bystander message {sfx}" in raw
        assert ok(c.get("/v1/me", headers=h("bystander")))["email"] == U["bystander"]["email"]
        assert items(ok(c.get("/v1/shipments", headers=h("bystander"))))
        assert c.get(f"/v1/media/files/{S['bystander']['image']}.png").status_code == 200, "bystander image gone"
        # partner is unaffected as well
        assert ok(c.get("/v1/me", headers=h("partner")))["id"] == U["partner"]["id"]

    step("isolation: bystander and partner data untouched", bystander_untouched)

    def anonymized_gateway():
        r = c.post("/v1/auth/register", json={"email": U["victim"]["email"], "password": PW, "name": "Again"})
        assert r.status_code in (201, 409), r.status_code  # email scrubbed (reusable) or reserved: both acceptable
        if r.status_code == 201:
            assert r.json()["user"]["id"] != U["victim"]["id"]

    step("delete: scrubbed gateway row does not resurrect the account", anonymized_gateway)


def main() -> int:
    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="ff-e2e-p-"))
    procs: list[subprocess.Popen] = []
    try:
        os.environ.update({"FF_FEED_ADMIN_TOKEN": ADMIN_TOKEN, "FF_FREIGHT_ADMIN_TOKEN": ADMIN_TOKEN})
        procs = e2e.start_services(tmp)
        e2e.wait_health(tmp)
        print("all services healthy")
        flow()
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
