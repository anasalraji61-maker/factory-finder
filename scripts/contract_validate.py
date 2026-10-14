#!/usr/bin/env python3
"""Validate real JSON responses of every service against contracts/openapi/<svc>.yaml.

Boots the 12 services as local processes (same startup as scripts/e2e.py: temp sqlite, mock providers),
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
        return r.json() if r.content else None


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
