#!/usr/bin/env python3
"""Validate real JSON responses of every service against contracts/openapi/<svc>.yaml.

Boots every service as local processes (same startup as scripts/e2e.py: temp sqlite, mock providers),
calls representative endpoints and validates each response body against the OpenAPI response schema
(JSON Schema 2020-12, `$ref` resolved across `#/components/...` and `../schemas/common.schema.json`).

    python scripts/contract_validate.py            # exit 1 on any non-allowlisted mismatch
    python scripts/contract_validate.py -v         # also list every validated call

Known / accepted drift lives in scripts/contract_validate.allow.json (a reason per entry).
Requires: pyyaml, jsonschema, referencing, httpx.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urljoin

import httpx
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import e2e  # noqa: E402  (reuses the process startup + health wait)

OPENAPI = ROOT / "contracts" / "openapi"
COMMON_ID = "https://factory-finder.dev/schemas/common.schema.json"
ALLOW_FILE = HERE / "contract_validate.allow.json"
VERBOSE = "-v" in sys.argv

PORTS = {n: p for n, (p, _) in e2e.SERVICES.items()}


# ---------------------------------------------------------------- validation core
def _retrieve(uri: str) -> Resource:
    if uri == COMMON_ID:
        uri = (ROOT / "contracts" / "schemas" / "common.schema.json").as_uri()
    path = Path(uri.removeprefix("file://"))
    text = path.read_text()
    data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    return Resource.from_contents(data, default_specification=DRAFT202012)


REGISTRY: Registry = Registry(retrieve=_retrieve)  # type: ignore[call-arg]
SPECS: dict[str, dict] = {n: yaml.safe_load((OPENAPI / f"{n}.yaml").read_text()) for n in PORTS}


def _norm_template(spec: dict, method: str, path: str) -> str | None:
    """Find the contract path template for a concrete path (templates may use any param name)."""
    import re

    for tpl in spec["paths"]:
        rx = "^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(tpl)) + "$"
        if re.match(rx, path) and method.lower() in spec["paths"][tpl]:
            return tpl
    return None


class Mismatch(tuple):
    """(spec, method, path_template, status, location, message)"""


MISMATCHES: list[tuple] = []
VALIDATED: list[tuple[str, str, str, int]] = []
UNCHECKED: list[tuple[str, str, str, int, str]] = []


def validate(spec_name: str, resp: httpx.Response, *, template: str | None = None) -> None:
    spec = SPECS[spec_name]
    method = resp.request.method
    path = resp.request.url.path
    tpl = template or _norm_template(spec, method, path)
    if tpl is None:
        MISMATCHES.append((spec_name, method, path, resp.status_code, "paths", "operation not in contract"))
        return
    op = spec["paths"][tpl][method.lower()]
    code = str(resp.status_code)
    responses = op.get("responses", {})
    key = code if code in responses else ("default" if "default" in responses else None)
    base = (OPENAPI / f"{spec_name}.yaml").as_uri()
    if key is None:
        MISMATCHES.append((spec_name, method, tpl, resp.status_code, f"responses.{code}", f"status {code} is not documented"))
        return
    rpointer = f"{base}#/paths/{quote(tpl.replace('~', '~0').replace('/', '~1'), safe='/~')}/{method.lower()}/responses/{key}"
    robj = responses[key]
    if "$ref" in robj:
        rpointer = urljoin(base, robj["$ref"])
        robj = REGISTRY.resolver(base).lookup(robj["$ref"]).contents
    media = (robj.get("content") or {}).get("application/json")
    if not media or "schema" not in media:
        UNCHECKED.append((spec_name, method, tpl, resp.status_code, "no response schema in contract"))
        return
    if not resp.content:
        if resp.status_code == 204:
            VALIDATED.append((spec_name, method, tpl, resp.status_code))
            return
        MISMATCHES.append((spec_name, method, tpl, resp.status_code, "body", "empty body but contract has a schema"))
        return
    try:
        body = resp.json()
    except ValueError:
        MISMATCHES.append((spec_name, method, tpl, resp.status_code, "body", "response is not JSON"))
        return
    v = Draft202012Validator({"$ref": f"{rpointer}/content/application~1json/schema"}, registry=REGISTRY)
    errs = sorted(v.iter_errors(body), key=lambda e: list(map(str, e.absolute_path)))
    VALIDATED.append((spec_name, method, tpl, resp.status_code))
    for e in errs:
        loc = "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in e.absolute_path)
        sp = "/".join(str(x) for x in list(e.absolute_schema_path)[-4:])
        MISMATCHES.append((spec_name, method, tpl, resp.status_code, loc, f"{e.message[:220]} (schema: {sp})"))


# ---------------------------------------------------------------- allowlist
def load_allow() -> list[dict]:
    if not ALLOW_FILE.exists():
        return []
    entries = json.loads(ALLOW_FILE.read_text())
    for e in entries:
        assert e.get("reason"), f"allowlist entry without reason: {e}"
    return entries


def allowed(entry: dict, m: tuple) -> bool:
    """Entry keys: spec, method ("*" = any), path (contract template, "*" = any), optional status,
    location (regex searched in the JSON path of the offending value), message_contains, reason."""
    spec, method, tpl, status, loc, msg = m
    return (
        entry["spec"] == spec
        and entry["method"] in ("*", method)
        and entry["path"] in ("*", tpl)
        and entry.get("status", status) == status
        and re.search(entry.get("location", ""), loc) is not None
        and entry.get("message_contains", "") in msg
    )


# ---------------------------------------------------------------- scenario
class Calls:
    def __init__(self) -> None:
        self.clients = {n: httpx.Client(base_url=f"http://localhost:{p}", timeout=30) for n, p in PORTS.items()}

    def call(self, svc: str, method: str, path: str, *, spec: str | None = None, want: tuple[int, ...] = (200, 201, 204), template: str | None = None, **kw) -> dict | list | None:
        r = self.clients[svc].request(method, path, **kw)
        if r.status_code not in want:
            MISMATCHES.append((spec or svc, method, template or path, r.status_code, "status", f"unexpected status (wanted {want}): {r.text[:160]}"))
            return None
        validate(spec or svc, r, template=template)
        if not r.content or not r.headers.get("content-type", "").startswith("application/json"):
            return None  # 204 / binary bodies (e.g. image bytes)
        return r.json()


def scenario() -> None:
    cl = Calls()
    c = cl.call
    sfx = uuid.uuid4().hex[:8]
    buyer, supplier = f"usr_buyer{sfx}", f"usr_supplier{sfx}"
    hb, hs = {"X-User-Id": buyer}, {"X-User-Id": supplier}
    adm = {"X-User-Id": "admin"}

    # -- health/ready of every service
    for n in PORTS:
        c(n, "GET", "/health", want=(200,))
        c(n, "GET", "/ready", want=(200,))

    # -- sourcing
    s = c("sourcing", "GET", "/v1/search", params={"q": "injection molding machine"}) or {}
    c("sourcing", "GET", "/v1/search", params={"q": "خط انتاج معجنات", "sort": "price_asc", "page_size": 5})
    c("sourcing", "GET", "/v1/search", params={"q": "machine", "sort": "trust", "kind": "product", "verified_only": "true"})
    c("sourcing", "GET", "/v1/search", params={"sort": "bogus"}, want=(422,))
    lst = (s.get("items") or [{}])[0]
    if lst.get("id"):
        c("sourcing", "GET", f"/v1/listings/{lst['id']}")
        sid = (lst.get("supplier") or {}).get("id")
        if sid:
            c("sourcing", "GET", f"/v1/suppliers/{sid}")
    c("sourcing", "GET", "/v1/listings/does-not-exist", want=(404,))
    c("sourcing", "GET", "/v1/categories")
    c("sourcing", "GET", "/v1/sources")
    # supplier-owned listings (X-Supplier-Id is what the gateway forwards for a verified claim)
    hsup = {"X-Supplier-Id": f"sup_cv{sfx}"}
    my_body = {
        "kind": "product", "title": f"Contract widget {sfx}", "category": "furniture", "unit": "piece", "moq": 10,
        "price": {"min": {"amount": "1.50", "currency": "USD"}, "max": {"amount": "2.00", "currency": "USD"}},
        "origin": {"country_code": "IQ", "city": "Baghdad"}, "lead_time_days": {"min": 3, "max": 7}, "hs_code": "940360",
        "images": ["https://example.com/a.jpg"], "specs": {"Color": "Blue"}, "description": "d",
    }
    c("sourcing", "POST", "/v1/my/listings", json=my_body, want=(403,))
    c("sourcing", "POST", "/v1/my/listings", json={**my_body, "moq": 0}, headers=hsup, want=(422,))
    mine = c("sourcing", "POST", "/v1/my/listings", json=my_body, headers=hsup, template="/v1/my/listings") or {}
    if mine.get("id"):
        mid = mine["id"]
        c("sourcing", "GET", "/v1/my/listings", headers=hsup)
        c("sourcing", "GET", f"/v1/my/listings/{mid}", headers=hsup, template="/v1/my/listings/{id}")
        c("sourcing", "PUT", f"/v1/my/listings/{mid}", json=my_body, headers=hsup, template="/v1/my/listings/{id}")
        c("sourcing", "GET", f"/v1/my/listings/{mid}", headers={"X-Supplier-Id": "sup_other"}, want=(404,), template="/v1/my/listings/{id}")
        c("sourcing", "POST", f"/v1/my/listings/{mid}/publish", headers=hsup, want=(200, 403, 503), template="/v1/my/listings/{id}/publish")
        c("sourcing", "POST", f"/v1/listings/{mid}/events", json={"type": "view"}, want=(202,), template="/v1/listings/{id}/events")
        c("sourcing", "GET", "/v1/my/analytics", headers=hsup, params={"days": 7})
        c("sourcing", "GET", "/v1/my/analytics", headers=hsup, params={"days": 30, "listing_id": mid})
        c("sourcing", "POST", f"/v1/my/listings/{mid}/unpublish", headers=hsup, want=(200, 409), template="/v1/my/listings/{id}/unpublish")
        c("sourcing", "DELETE", f"/v1/my/listings/{mid}", headers=hsup, want=(204,), template="/v1/my/listings/{id}")

    # -- logistics
    quote_body = {
        "goods": {"description": "chairs", "quantity": 500, "total_value": {"amount": "5000", "currency": "USD"}, "total_weight_kg": 3000, "total_volume_m3": 30},
        "origin": {"country_code": "CN", "city": "Shanghai"}, "destination": {"country_code": "IQ", "city": "Baghdad"}, "display_currency": "USD",
    }
    c("logistics", "POST", "/v1/quotes/landed-cost", json=quote_body)
    c("logistics", "POST", "/v1/quotes/landed-cost", json={"goods": {}}, want=(422,))
    c("logistics", "GET", "/v1/fx/rates")
    c("logistics", "POST", "/v1/fx/convert", json={"amount": "100", "from": "USD", "to": "IQD"})
    c("logistics", "GET", "/v1/carriers")
    c("logistics", "GET", "/v1/hs/search", params={"q": "chair"})
    c("logistics", "GET", "/v1/hs/search", params={"q": "9403"})
    c("logistics", "GET", "/v1/hs/940360")

    # -- geo
    c("geo", "GET", "/v1/countries")
    c("geo", "GET", "/v1/cities", params={"country": "IQ"})
    c("geo", "GET", "/v1/hubs")
    c("geo", "GET", "/v1/hubs/nearest", params={"lat": 33.3, "lon": 44.4, "limit": 3})
    for mode in ("road", "sea", "air"):
        c("geo", "GET", "/v1/distance", params={"from_lat": 31.2, "from_lon": 121.5, "to_lat": 33.3, "to_lon": 44.4, "mode": mode})
    c("geo", "GET", "/v1/distance", params={"from_lat": 31.2}, want=(422,))

    # -- trust
    sid = (lst.get("supplier") or {}).get("id") or "sup_demo"
    c("trust", "GET", f"/v1/trust/suppliers/{sid}")
    c("trust", "GET", f"/v1/trust/suppliers/{sid}/history")
    c("trust", "GET", "/v1/trust/suppliers:batch", params={"ids": sid})
    c("trust", "GET", "/v1/trust/suppliers/zzz-unknown", want=(200, 404))

    # -- rfq
    rq = c("rfq", "POST", "/v1/requests", headers=hb, json={
        "kind": "product", "title": "Plastic chairs 500", "quantity": 500, "unit": "piece",
        "target_price": {"amount": "8", "currency": "USD"}, "destination": {"country_code": "IQ", "city": "Erbil"}}) or {}
    deal_id = None
    if rq.get("id"):
        rid = rq["id"]
        c("rfq", "GET", f"/v1/requests/{rid}", headers=hb)
        c("rfq", "GET", "/v1/requests", headers=hb)
        c("rfq", "GET", f"/v1/requests/{rid}/suggestions", headers=hb)
        off = c("rfq", "POST", f"/v1/requests/{rid}/offers", headers=hs, json={
            "price": {"amount": "7.5", "currency": "USD"}, "supplier_name": "Supplier One", "moq": 100, "lead_time_days": 20, "incoterm": "FOB"}) or {}
        c("rfq", "GET", f"/v1/requests/{rid}/offers", headers=hb)
        if off.get("id"):
            acc = c("rfq", "POST", f"/v1/offers/{off['id']}/accept", headers=hb) or {}
            deal_id = (acc.get("deal") or acc).get("id") or acc.get("deal_id")
        if deal_id:
            c("rfq", "GET", f"/v1/deals/{deal_id}", headers=hb)
            # a fresh deal is pending_payment -> not reviewable yet (409); success shapes are covered by rfq tests
            c("rfq", "POST", f"/v1/deals/{deal_id}/reviews", headers=hb, json={"rating": 5, "title": "Good"}, want=(409,))
            c("rfq", "POST", f"/v1/deals/{deal_id}/reviews", headers=hb, json={"rating": 9}, want=(422,))
    c("rfq", "GET", "/v1/suppliers/sup_cv_none/reviews", params={"sort": "rating", "page_size": 5})
    c("rfq", "GET", "/v1/suppliers/sup_cv_none/review-summary")
    c("rfq", "PUT", "/v1/reviews/rev_nope", headers=hb, json={"rating": 4}, want=(404,))
    c("rfq", "DELETE", "/v1/reviews/rev_nope", headers=hb, want=(404,))
    c("rfq", "POST", "/v1/reviews/rev_nope/reply", headers=hs, json={"text": "thanks"}, want=(404,))
    c("rfq", "POST", "/v1/reviews/rev_nope/report", headers=hb, json={"reason": "spam"}, want=(404,))
    c("rfq", "GET", "/v1/requests/nope", headers=hb, want=(404,))

    # -- messaging
    cv = c("messaging", "POST", "/v1/conversations", headers=hb, json={
        "participants": [{"user_id": supplier, "role": "supplier"}], "my_role": "buyer", "context": {"type": "listing", "ref_id": lst.get("id", "x")}}) or {}
    if cv.get("id"):
        c("messaging", "POST", f"/v1/conversations/{cv['id']}/messages", headers=hb, json={"type": "text", "text": "Hello, price for 500?"})
        c("messaging", "GET", f"/v1/conversations/{cv['id']}", headers=hs)
        c("messaging", "GET", f"/v1/conversations/{cv['id']}/messages", headers=hs)
        c("messaging", "POST", f"/v1/conversations/{cv['id']}/read", headers=hs, json={})
    c("messaging", "GET", "/v1/conversations", headers=hs)

    # -- tracking
    sh = c("tracking", "POST", "/v1/shipments", headers=hb, json={"reference": "CSQU3054383", "reference_type": "container", "label": "chairs"}) or {}
    if sh.get("id"):
        c("tracking", "GET", f"/v1/shipments/{sh['id']}", headers=hb)
        c("tracking", "POST", f"/v1/shipments/{sh['id']}/refresh", headers=hb, want=(200, 202, 429))
    c("tracking", "GET", "/v1/shipments", headers=hb)
    c("tracking", "GET", "/v1/validate/container/CSQU3054383", headers=hb)

    # -- notifications
    w = c("notifications", "POST", "/v1/watchlist", headers=hb, json={"listing_id": lst.get("id", "x")}) or {}
    c("notifications", "POST", "/v1/watchlist", headers=hb, json={"search": {"q": "machine", "kind": "product"}, "drop_threshold_pct": "10"})
    c("notifications", "GET", "/v1/watchlist", headers=hb)
    c("notifications", "POST", "/v1/alerts/evaluate", json={"owner_id": buyer})
    c("notifications", "GET", "/v1/alerts", headers=hb)
    c("notifications", "POST", "/v1/alerts/read-all", headers=hb, want=(200, 204))
    c("notifications", "GET", "/v1/notification-prefs", headers=hb)
    c("notifications", "PUT", "/v1/notification-prefs", headers=hb, json={"language": "en", "timezone": "Asia/Baghdad", "quiet_hours": {"start": "22:00", "end": "07:00"}})
    c("notifications", "POST", "/v1/notification-prefs/verify-email", headers=hb, json={"code": "000000"}, want=(409, 422))
    c("notifications", "POST", "/v1/notification-prefs/resend-code", headers=hb, want=(409,))
    c("notifications", "POST", "/v1/devices", headers=hb, json={"token": f"tok-{sfx}", "platform": "android"}, want=(200, 201, 422))
    c("notifications", "GET", "/v1/devices", headers=hb)
    if w.get("id"):
        c("notifications", "DELETE", f"/v1/watchlist/{w['id']}", headers=hb, want=(204,))

    # -- assistant
    c("assistant", "POST", "/v1/assistant/query", headers=hb, json={"text": "ابي ٥٠٠ كرسي بلاستك من الصين الى اربيل", "locale": "ar"})
    c("assistant", "POST", "/v1/assistant/query", headers=hb, json={"text": "I need 200 injection molding machines from China to Dubai", "locale": "en"})

    # -- demand
    sg = c("demand", "POST", "/v1/signals", headers=adm, json={"text": "ابحث عن مورد كراسي بلاستيك 500 قطعة الى اربيل", "url": f"https://example.com/p/{sfx}"}) or {}
    c("demand", "POST", "/v1/signals/poll", headers=adm)
    c("demand", "GET", "/v1/signals", headers=adm)
    sig_id = (sg.get("signal") or sg).get("id")
    if sig_id:
        c("demand", "GET", f"/v1/signals/{sig_id}", headers=adm)
    dr = c("demand", "GET", "/v1/drafts", headers=adm) or {}
    c("demand", "GET", "/v1/quota", headers=adm)
    if dr.get("items"):
        did = dr["items"][0]["id"]
        c("demand", "GET", f"/v1/drafts/{did}", headers=adm)
        c("demand", "POST", f"/v1/drafts/{did}/approve", headers=adm, json={}, want=(200, 403))
        c("demand", "POST", f"/v1/drafts/{did}/mark-published", headers=adm, json={}, want=(200, 403, 409, 422))
    c("demand", "GET", "/v1/signals/nope", headers=adm, want=(404,))

    # -- payments
    if deal_id:
        inv = c("payments", "POST", "/v1/invoices", headers=hb, json={"deal_id": deal_id, "kind": "commission"}) or {}
        if inv.get("id"):
            c("payments", "POST", "/v1/invoices", headers=hb, json={"deal_id": deal_id, "kind": "commission"})
            c("payments", "GET", f"/v1/invoices/{inv['id']}", headers=hb)
            c("payments", "GET", "/v1/invoices", headers=hb)
            c("payments", "GET", "/v1/ledger", headers={"X-Admin-Token": e2e.ADMIN_TOKEN}, params={"invoice_id": inv["id"]})
            c("payments", "POST", f"/v1/invoices/{inv['id']}/cancel", headers=hb)
        c("payments", "POST", "/v1/payments/sweep", headers={"X-Admin-Token": e2e.ADMIN_TOKEN})
    c("payments", "GET", "/v1/invoices/nope", headers=hb, want=(404,))

    # -- media (multipart upload; image bytes are not JSON so GET /files is only status-checked)
    import struct
    import zlib

    def _chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes((x * 5 + y + int(sfx, 16)) % 256 for x in range(8) for _ in range(3)) for y in range(8))
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b"")
    up = c("media", "POST", "/v1/media/images", headers=hb, files={"file": ("a.png", png, "image/png")}, data={"kind": "avatar"}) or {}
    c("media", "POST", "/v1/media/images", headers=hb, files={"file": ("a.png", png, "image/png")}, want=(200,))
    c("media", "POST", "/v1/media/images", headers=hb, files={"file": ("a.png", b"<html></html>", "image/png")}, want=(415,))
    c("media", "POST", "/v1/media/images", headers=hb, files={"file": ("a.png", png, "image/png")}, data={"kind": "x"}, want=(422,))
    c("media", "POST", "/v1/media/images", files={"file": ("a.png", png, "image/png")}, want=(401,))
    if up.get("id"):
        c("media", "GET", f"/v1/media/files/{up['id']}.png", template="/v1/media/files/{filename}", want=(200,))
        c("media", "GET", f"/v1/media/files/{up['id']}.png", params={"w": 100}, template="/v1/media/files/{filename}", want=(422,))
        c("media", "DELETE", f"/v1/media/images/{up['id']}", headers=hs, want=(404,))
        c("media", "DELETE", f"/v1/media/images/{up['id']}", headers=hb, want=(204,))
    c("media", "GET", f"/v1/media/files/{'0' * 32}.png", template="/v1/media/files/{filename}", want=(404,))
    pv = c("media", "POST", "/v1/media/images", headers=hb, files={"file": ("a.png", png, "image/png")}, data={"kind": "verification"}) or {}
    if pv.get("id"):
        c("media", "POST", f"/v1/media/files/{pv['id']}/sign", headers=hb, template="/v1/media/files/{id}/sign", want=(200,))
        c("media", "POST", f"/v1/media/files/{pv['id']}/sign", headers=hs, template="/v1/media/files/{id}/sign", want=(404,))
        c("media", "GET", f"/v1/media/private/{pv['id']}.png", headers=hb, template="/v1/media/private/{filename}", want=(200,))
        c("media", "GET", f"/v1/media/private/{pv['id']}.png", template="/v1/media/private/{filename}", want=(404,))
        c("media", "GET", f"/v1/media/files/{pv['id']}.png", template="/v1/media/files/{filename}", want=(404,))
        c("media", "DELETE", f"/v1/media/images/{pv['id']}", headers=hb, want=(204,))

    # -- feed (identity headers as the gateway would forward them; admin routes need the service admin token)
    fsup = f"sup_feed{sfx}"
    ad_feed = {"X-Admin-Token": e2e.ADMIN_TOKEN}
    hfs = {"X-User-Id": supplier, "X-Supplier-Id": fsup}
    fp = c("feed", "POST", "/v1/feed/posts", headers=hfs, json={"body": "New stock of ceramic planters", "tags": ["Planters"], "listing_ref": "lst_1"}) or {}
    c("feed", "POST", "/v1/feed/posts", headers=hb, json={"body": "x"}, want=(403,))
    c("feed", "POST", "/v1/feed/posts", headers=hfs, json={"body": "mail me a@b.com"}, want=(422,))
    c("feed", "GET", "/v1/feed/trending")
    c("feed", "GET", "/v1/feed/home", headers=hb)
    c("feed", "GET", "/v1/feed/home", headers=hb, params={"cursor": "bad"}, want=(422,))
    c("feed", "POST", f"/v1/feed/suppliers/{fsup}/follow", headers=hb, template="/v1/feed/suppliers/{supplier_id}/follow")
    c("feed", "GET", "/v1/feed/following", headers=hb)
    c("feed", "GET", f"/v1/feed/suppliers/{fsup}/posts", headers=hb, template="/v1/feed/suppliers/{supplier_id}/posts")
    if fp.get("id"):
        fid = fp["id"]
        c("feed", "GET", f"/v1/feed/posts/{fid}", headers=hb, template="/v1/feed/posts/{post_id}")
        c("feed", "PUT", f"/v1/feed/posts/{fid}/like", headers=hb, template="/v1/feed/posts/{post_id}/like")
        c("feed", "DELETE", f"/v1/feed/posts/{fid}/like", headers=hb, template="/v1/feed/posts/{post_id}/like")
        fc = c("feed", "POST", f"/v1/feed/posts/{fid}/comments", headers=hb, json={"body": "Interested"}, template="/v1/feed/posts/{post_id}/comments") or {}
        c("feed", "GET", f"/v1/feed/posts/{fid}/comments", headers=hb, template="/v1/feed/posts/{post_id}/comments")
        c("feed", "POST", f"/v1/feed/posts/{fid}/report", headers=hb, json={"reason": "spam"}, want=(202,), template="/v1/feed/posts/{post_id}/report")
        c("feed", "GET", "/v1/admin/feed/posts", headers=ad_feed, params={"status": "all"})
        c("feed", "POST", f"/v1/admin/feed/posts/{fid}/hide", headers=ad_feed, json={"reason": "contract check"}, template="/v1/admin/feed/posts/{post_id}/hide")
        c("feed", "POST", f"/v1/admin/feed/posts/{fid}/restore", headers=ad_feed, template="/v1/admin/feed/posts/{post_id}/restore")
        c("feed", "GET", "/v1/admin/feed/reports", headers=ad_feed, params={"target_id": fid})
        if fc.get("id"):
            cid = fc["id"]
            c("feed", "POST", f"/v1/feed/comments/{cid}/report", headers=hs, json={"reason": "other"}, want=(202,), template="/v1/feed/comments/{comment_id}/report")
            c("feed", "POST", f"/v1/admin/feed/comments/{cid}/hide", headers=ad_feed, json={"reason": "contract check"}, template="/v1/admin/feed/comments/{comment_id}/hide")
            c("feed", "GET", "/v1/admin/feed/comments", headers=ad_feed, params={"status": "all"})
            c("feed", "POST", f"/v1/admin/feed/comments/{cid}/restore", headers=ad_feed, template="/v1/admin/feed/comments/{comment_id}/restore")
            c("feed", "DELETE", f"/v1/feed/comments/{cid}", headers=hb, want=(204,), template="/v1/feed/comments/{comment_id}")
        c("feed", "DELETE", f"/v1/feed/posts/{fid}", headers=hfs, want=(204,), template="/v1/feed/posts/{post_id}")
    c("feed", "GET", "/v1/feed/posts/post_nope", headers=hb, want=(404,), template="/v1/feed/posts/{post_id}")
    c("feed", "DELETE", f"/v1/feed/suppliers/{fsup}/follow", headers=hb, template="/v1/feed/suppliers/{supplier_id}/follow")

    # -- freight (identity as the gateway would forward it; admin routes need the service admin token)
    ad_fr = {"X-Admin-Token": e2e.ADMIN_TOKEN}
    hfw, hfw2, hbuy2 = {"X-User-Id": f"usr_fwd{sfx}"}, {"X-User-Id": f"usr_fwd2{sfx}"}, {"X-User-Id": f"usr_buyer2{sfx}"}
    lanes = [{"origin_country": "CN", "destination_country": "IQ"}, {"origin_country": "*", "destination_country": "AE"}]
    fapp = {"company_name": f"Contract Freight {sfx}", "country_code": "AE", "description": "Sea freight", "lanes": lanes,
            "modes": ["sea", "air"], "incoterms": ["FOB", "CIF"], "certifications": ["FIATA"]}  # fmt: skip
    a1 = c("freight", "POST", "/v1/freight/applications", headers=hfw, json=fapp) or {}
    c("freight", "POST", "/v1/freight/applications", headers=hfw, json=fapp, want=(409,))
    c("freight", "POST", "/v1/freight/applications", headers=hfw, json={**fapp, "modes": []}, want=(422,))
    c("freight", "POST", "/v1/freight/applications", json=fapp, want=(401,))
    c("freight", "GET", "/v1/freight/applications/mine", headers=hfw)
    c("freight", "GET", "/v1/freight/me", headers=hfw)
    c("freight", "GET", "/v1/freight/forwarders/me", headers=hfw, want=(403,))
    a2 = c("freight", "POST", "/v1/freight/applications", headers=hfw2, json={**fapp, "company_name": f"Other Freight {sfx}"}) or {}
    c("freight", "GET", "/v1/admin/freight/applications", headers=ad_fr, params={"status": "all"})
    c("freight", "GET", "/v1/admin/freight/applications", want=(401,))
    if a2.get("id"):
        c("freight", "POST", f"/v1/admin/freight/applications/{a2['id']}/reject", headers=ad_fr, json={"reason": "incomplete documents"}, template="/v1/admin/freight/applications/{application_id}/reject")
    fid = ""
    if a1.get("id"):
        ap = c("freight", "POST", f"/v1/admin/freight/applications/{a1['id']}/approve", headers=ad_fr, json={"note": "checked"}, template="/v1/admin/freight/applications/{application_id}/approve") or {}
        c("freight", "POST", f"/v1/admin/freight/applications/{a1['id']}/approve", headers=ad_fr, template="/v1/admin/freight/applications/{application_id}/approve")
        c("freight", "POST", f"/v1/admin/freight/applications/{a1['id']}/reject", headers=ad_fr, json={"reason": "late"}, want=(409,), template="/v1/admin/freight/applications/{application_id}/reject")
        fid = ap.get("forwarder_id") or ""
    if fid:
        c("freight", "GET", "/v1/freight/forwarders/me", headers=hfw)
        c("freight", "PATCH", "/v1/freight/forwarders/me", headers=hfw, json={"description": "Sea and air freight", "certifications": ["FIATA", "ISO 9001"]})
        c("freight", "GET", "/v1/freight/forwarders", headers=hb, params={"origin_country": "CN", "destination_country": "IQ", "mode": "sea", "incoterm": "FOB"})
        c("freight", "GET", f"/v1/freight/forwarders/{fid}", headers=hb, template="/v1/freight/forwarders/{forwarder_id}")
        c("freight", "GET", f"/v1/freight/forwarders/{fid}/ratings", headers=hb, template="/v1/freight/forwarders/{forwarder_id}/ratings")
        c("freight", "GET", "/v1/admin/freight/forwarders", headers=ad_fr)
    c("freight", "GET", "/v1/freight/forwarders/fwd_nope", headers=hb, want=(404,), template="/v1/freight/forwarders/{forwarder_id}")
    c("freight", "GET", "/v1/freight/forwarders", headers=hb, params={"mode": "boat"}, want=(422,))
    ready = (datetime.now(UTC) + timedelta(days=7)).date().isoformat()
    sreq = {"origin_country": "CN", "origin_place": "Shenzhen", "destination_country": "IQ", "destination_place": "Umm Qasr",
            "cargo_description": f"Contract ceramic tiles {sfx}", "hs_code": "6907.21", "weight_kg": "18000", "volume_cbm": "28.5",
            "mode": "sea", "container_type": "40HC", "container_count": 1, "incoterm": "FOB", "ready_date": ready,
            "currency": "USD", "landed_cost_ref": "qt_contract"}  # fmt: skip
    c("freight", "POST", "/v1/freight/requests", headers=hb, json={**sreq, "cargo_description": "mail me boss@example.com"}, want=(422,))
    c("freight", "POST", "/v1/freight/requests", headers=hb, json={**sreq, "mode": "air"}, want=(422,))
    rq = c("freight", "POST", "/v1/freight/requests", headers=hb, json=sreq) or {}
    rq2 = c("freight", "POST", "/v1/freight/requests", headers=hbuy2, json=sreq) or {}
    c("freight", "GET", "/v1/freight/requests", headers=hb, params={"status": "open"})
    if rq.get("id") and fid:
        rid = rq["id"]
        tq = "/v1/freight/requests/{request_id}"
        c("freight", "GET", f"/v1/freight/requests/{rid}", headers=hb, template=tq)
        c("freight", "GET", f"/v1/freight/requests/{rid}", headers=hfw, template=tq)
        c("freight", "GET", f"/v1/freight/requests/{rid}", headers=hfw2, want=(404,), template=tq)
        c("freight", "GET", "/v1/freight/forwarders/me/inbox", headers=hfw)
        qb = {"amount": "2450.00", "currency": "USD", "transit_days": 28, "valid_days": 14, "inclusions": ["Ocean freight"],
              "exclusions": ["Duties"], "breakdown": [{"label": "Ocean freight", "amount": "2000.00"}, {"label": "Origin charges", "amount": "450.00"}], "terms": "Net 14 days"}  # fmt: skip
        c("freight", "POST", f"/v1/freight/requests/{rid}/quotes", headers=hb, json=qb, want=(403,), template=tq + "/quotes")
        c("freight", "POST", f"/v1/freight/requests/{rid}/quotes", headers=hfw, json={**qb, "currency": "EUR"}, want=(422,), template=tq + "/quotes")
        c("freight", "POST", f"/v1/freight/requests/{rid}/quotes", headers=hfw, json={**qb, "terms": "call +964 770 123 4567"}, want=(422,), template=tq + "/quotes")
        q = c("freight", "POST", f"/v1/freight/requests/{rid}/quotes", headers=hfw, json=qb, template=tq + "/quotes") or {}
        c("freight", "POST", f"/v1/freight/requests/{rid}/quotes", headers=hfw, json=qb, want=(409,), template=tq + "/quotes")
        c("freight", "GET", f"/v1/freight/requests/{rid}/quotes", headers=hb, template=tq + "/quotes")
        for srt in ("score", "price", "transit", "rating"):
            c("freight", "GET", f"/v1/freight/requests/{rid}/comparison", headers=hb, params={"sort": srt}, template=tq + "/comparison")
        c("freight", "GET", f"/v1/freight/requests/{rid}/comparison", headers=hb, params={"sort": "luck"}, want=(422,), template=tq + "/comparison")
        c("freight", "GET", "/v1/freight/forwarders/me/quotes", headers=hfw)
        if q.get("id"):
            qid, tqq = q["id"], "/v1/freight/quotes/{quote_id}"
            c("freight", "GET", f"/v1/freight/quotes/{qid}", headers=hb, template=tqq)
            c("freight", "PUT", f"/v1/freight/quotes/{qid}", headers=hfw, json={**qb, "amount": "2400.00", "breakdown": [{"label": "All-in", "amount": "2400.00"}]}, template=tqq)
            c("freight", "POST", f"/v1/freight/quotes/{qid}/report", headers=hb, json={"reason": "misleading", "details": "check a@b.com"}, want=(202,), template=tqq + "/report")
            c("freight", "POST", f"/v1/freight/requests/{rid}/report", headers=hfw, json={"reason": "spam"}, want=(202,), template=tq + "/report")
            c("freight", "POST", f"/v1/freight/forwarders/{fid}/report", headers=hb, json={"reason": "other"}, want=(202,), template="/v1/freight/forwarders/{forwarder_id}/report")
            c("freight", "POST", f"/v1/freight/quotes/{qid}/withdraw", headers=hfw, template=tqq + "/withdraw")
            c("freight", "PUT", f"/v1/freight/quotes/{qid}", headers=hfw, json=qb, template=tqq)
            c("freight", "POST", f"/v1/freight/quotes/{qid}/accept", headers=hfw, want=(404,), template=tqq + "/accept")
            c("freight", "POST", f"/v1/freight/requests/{rid}/rating", headers=hb, json={"stars": 5}, want=(409,), template=tq + "/rating")
            c("freight", "POST", f"/v1/freight/quotes/{qid}/accept", headers=hb, template=tqq + "/accept")
            c("freight", "POST", f"/v1/freight/quotes/{qid}/accept", headers=hb, template=tqq + "/accept")
            c("freight", "GET", f"/v1/freight/requests/{rid}/comparison", headers=hb, template=tq + "/comparison")
            c("freight", "POST", f"/v1/freight/requests/{rid}/close", headers=hb, template=tq + "/close")
            c("freight", "POST", f"/v1/freight/requests/{rid}/rating", headers=hb, json={"stars": 4, "comment": "Reliable"}, template=tq + "/rating")
            c("freight", "POST", f"/v1/freight/requests/{rid}/rating", headers=hb, json={"stars": 4}, want=(409,), template=tq + "/rating")
            c("freight", "GET", f"/v1/freight/forwarders/{fid}/ratings", headers=hb, template="/v1/freight/forwarders/{forwarder_id}/ratings")
            c("freight", "GET", "/v1/admin/freight/quotes", headers=ad_fr, params={"request_id": rid})
            c("freight", "POST", f"/v1/admin/freight/quotes/{qid}/hide", headers=ad_fr, json={"reason": "contract check"}, template="/v1/admin/freight/quotes/{quote_id}/hide")
            c("freight", "POST", f"/v1/admin/freight/quotes/{qid}/restore", headers=ad_fr, template="/v1/admin/freight/quotes/{quote_id}/restore")
            c("freight", "GET", "/v1/admin/freight/reports", headers=ad_fr, params={"target_id": qid})
        c("freight", "POST", f"/v1/admin/freight/requests/{rid}/hide", headers=ad_fr, json={"reason": "contract check"}, template="/v1/admin/freight/requests/{request_id}/hide")
        c("freight", "GET", "/v1/admin/freight/requests", headers=ad_fr, params={"visibility": "hidden"})
        c("freight", "POST", f"/v1/admin/freight/requests/{rid}/restore", headers=ad_fr, template="/v1/admin/freight/requests/{request_id}/restore")
        c("freight", "POST", f"/v1/admin/freight/forwarders/{fid}/suspend", headers=ad_fr, json={"reason": "contract check"}, template="/v1/admin/freight/forwarders/{forwarder_id}/suspend")
        c("freight", "POST", f"/v1/admin/freight/forwarders/{fid}/reinstate", headers=ad_fr, template="/v1/admin/freight/forwarders/{forwarder_id}/reinstate")
    if rq2.get("id"):
        c("freight", "POST", f"/v1/freight/requests/{rq2['id']}/close", headers=hbuy2, template="/v1/freight/requests/{request_id}/close")
    c("freight", "POST", "/v1/admin/freight/sweep", headers=ad_fr)
    c("freight", "GET", "/v1/freight/requests/shp_nope", headers=hb, want=(404,), template="/v1/freight/requests/{request_id}")

    # -- gateway (own routes; admin-demand proxy is validated against the demand contract)
    gw = httpx.Client(base_url=e2e.GW, timeout=30)
    gcall = Calls()
    gcall.clients["gateway"] = gw
    email = f"cv{sfx}@example.com"
    reg = gcall.call("gateway", "POST", "/v1/auth/register", json={"email": email, "password": "Passw0rd!x", "name": "CV User"}) or {}
    gcall.call("gateway", "POST", "/v1/auth/login", json={"email": email, "password": "Passw0rd!x"})
    if reg.get("refresh_token"):
        gcall.call("gateway", "POST", "/v1/auth/refresh", json={"refresh_token": reg["refresh_token"]})
    gcall.call("gateway", "POST", "/v1/auth/login", json={"email": email, "password": "wrong"}, want=(401,))
    if reg.get("access_token"):
        ah = {"Authorization": f"Bearer {reg['access_token']}"}
        gcall.call("gateway", "GET", "/v1/me", headers=ah)
        gcall.call("gateway", "PATCH", "/v1/me", headers=ah, json={"company": "ACME", "default_destination": {"country_code": "IQ", "city": "Baghdad"}})
        gcall.call("gateway", "GET", "/v1/home", headers=ah)
        gcall.call("gateway", "GET", "/v1/me", want=(401,))
        # proxied: gateway responses must satisfy the owning service's contract too
        gcall.call("gateway", "GET", "/v1/trust/suppliers/" + sid, spec="trust", headers=ah)
        gcall.call("gateway", "GET", "/v1/hs/search", spec="logistics", headers=ah, params={"q": "chair"})
        gcall.call("gateway", "GET", "/v1/notification-prefs", spec="notifications", headers=ah)
    ad = {"X-Admin-Token": e2e.ADMIN_TOKEN}
    gcall.call("gateway", "GET", "/v1/admin/overview", headers=ad)
    gcall.call("gateway", "GET", "/v1/admin/supplier-claims", headers=ad)
    gcall.call("gateway", "GET", "/v1/admin/demand/quota", spec="demand", headers=ad, template="/v1/quota")
    gcall.call("gateway", "GET", "/v1/admin/demand/signals", spec="demand", headers=ad, template="/v1/signals")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ff-cv-"))
    procs: list[subprocess.Popen] = []
    try:
        procs = e2e.start_services(tmp)
        e2e.wait_health(tmp)
        scenario()
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    allow = load_allow()
    used: set[int] = set()
    bad, acc = [], []
    for m in dict.fromkeys(MISMATCHES):  # de-duplicate repeated identical findings
        hit = next((i for i, e in enumerate(allow) if allowed(e, m)), None)
        if hit is None:
            bad.append(m)
        else:
            used.add(hit)
            acc.append((m, allow[hit]["reason"]))
    if VERBOSE:
        for s, m, t, st in VALIDATED:
            print(f"ok    {s}: {m} {t} -> {st}")
    for s, m, t, st, why in UNCHECKED:
        if VERBOSE:
            print(f"skip  {s}: {m} {t} -> {st} ({why})")
    for m, why in acc:
        print(f"ALLOW {m[0]} {m[1]} {m[2]} [{m[3]}] {m[4]}: {m[5]}\n      reason: {why}")
    for m in bad:
        print(f"DRIFT {m[0]} {m[1]} {m[2]} [{m[3]}] at {m[4]}: {m[5]}")
    for i, e in enumerate(allow):
        if i not in used:
            print(f"STALE allowlist entry (no longer matches anything): {e['spec']} {e['method']} {e['path']}")
    eps = {(s, m, t) for s, m, t, _ in VALIDATED}
    print(f"\n{len(VALIDATED)} responses validated across {len(eps)} distinct operations "
          f"({len(UNCHECKED)} without schema); {len(bad)} mismatches, {len(acc)} allowlisted")
    return 1 if bad or not VALIDATED else 0


if __name__ == "__main__":
    sys.exit(main())
