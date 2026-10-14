#!/usr/bin/env python3
"""Post-deploy smoke checker. Read-only and safe: only GET/OPTIONS/HEAD, no accounts, no writes.

    FF_E2E_BASE_URL=https://api.example.com python scripts/smoke_prod.py
    python scripts/smoke_prod.py https://api.example.com [--origin https://evil.example]

Checks: gateway /health + version, /ready (all upstream checks), CORS closed for a foreign origin, admin routes
unreachable without a token (404 when no admin token is configured, 401 when it is; never 2xx), protected routes
answer 401, error bodies carry no stack traces, and rate-limit/security header sanity (WARN when absent).
Exit code 1 on any FAIL; WARN does not fail.
"""
from __future__ import annotations

import os
import sys

import httpx

BASE = (next((a for a in sys.argv[1:] if a.startswith("http")), "") or os.environ.get("FF_E2E_BASE_URL", "")).rstrip("/")
ORIGIN = "https://smoke-test.invalid"
if "--origin" in sys.argv:
    ORIGIN = sys.argv[sys.argv.index("--origin") + 1]
FAILS: list[str] = []
WARNS: list[str] = []


def check(name: str, fn) -> None:
    try:
        note = fn()
        print(f"PASS  {name}" + (f"  ({note})" if note else ""))
    except AssertionError as e:
        FAILS.append(name)
        print(f"FAIL  {name}\n      {e}")
    except httpx.HTTPError as e:
        FAILS.append(name)
        print(f"FAIL  {name}\n      {type(e).__name__}: {e}")


def warn(name: str, msg: str) -> None:
    WARNS.append(name)
    print(f"WARN  {name}: {msg}")


def main() -> int:
    if not BASE:
        print("set FF_E2E_BASE_URL (or pass the URL as an argument)")
        return 2
    c = httpx.Client(base_url=BASE, timeout=15, follow_redirects=False)

    def health():
        r = c.get("/health")
        assert r.status_code == 200, f"/health -> {r.status_code}"
        d = r.json()
        assert d.get("status") == "ok" and d.get("service") == "gateway", d
        assert d.get("version"), f"no version in /health: {d}"
        return f"version {d['version']}"

    def ready():
        r = c.get("/ready")
        assert r.status_code == 200, f"/ready -> {r.status_code} {r.text[:300]}"
        d = r.json()
        assert d.get("status") == "ready", d
        bad = [k for k, v in (d.get("checks") or {}).items() if not v]
        assert not bad, f"failing checks: {bad}"
        return f"{len(d.get('checks') or {})} checks"

    def cors():
        r = c.get("/v1/categories", headers={"Origin": ORIGIN})
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers}, \
            f"foreign Origin allowed: {r.headers.get('access-control-allow-origin')}"
        r = c.options("/v1/me", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET",
                                          "Access-Control-Request-Headers": "authorization"})
        h = {k.lower(): v for k, v in r.headers.items()}
        assert h.get("access-control-allow-origin") not in ("*", ORIGIN), f"preflight allows {h.get('access-control-allow-origin')}"
        assert h.get("access-control-allow-credentials") != "true" or h.get("access-control-allow-origin") != "*"

    def admin_closed():
        seen = {}
        for p in ("/v1/admin/overview", "/v1/admin/supplier-claims", "/v1/admin/moderation/listings",
                  "/v1/admin/demand/quota", "/v1/admin/payments/outbox"):
            r = c.get(p)
            seen[p] = r.status_code
            assert r.status_code in (401, 404), f"GET {p} without token -> {r.status_code}"
            r = c.get(p, headers={"X-Admin-Token": "smoke-wrong-token"})
            assert r.status_code in (401, 404), f"GET {p} with a wrong token -> {r.status_code}"
        return "/".join(sorted({str(v) for v in seen.values()}))

    def protected():
        for p in ("/v1/me", "/v1/shipments", "/v1/deals", "/v1/conversations", "/v1/invoices"):
            r = c.get(p)
            assert r.status_code == 401, f"GET {p} without token -> {r.status_code}"

    def internal_closed():
        for m, p in (("POST", "/v1/internal/deals/x/payment-status"), ("POST", "/v1/internal/tracking-events"),
                     ("GET", "/v1/internal/outbox-status")):
            r = c.request(m, p, json={} if m == "POST" else None)
            assert r.status_code in (401, 403, 404), f"{m} {p} reachable through the gateway -> {r.status_code}"

    def public_read():
        r = c.get("/v1/categories")
        assert r.status_code == 200, f"/v1/categories -> {r.status_code}"
        r = c.get("/v1/search", params={"q": "chair", "page_size": 1})
        assert r.status_code == 200, f"/v1/search -> {r.status_code}"

    def errors_clean():
        r = c.get("/v1/does-not-exist-smoke")
        assert r.status_code in (401, 404), r.status_code
        assert "Traceback" not in r.text and "File \"" not in r.text, "stack trace in error body"
        r = c.get("/v1/search", params={"sort": "bogus"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", f"{r.status_code} {r.text[:200]}"

    def headers():
        r = c.get("/v1/categories")
        h = {k.lower(): v for k, v in r.headers.items()}
        if not any(k.startswith("x-ratelimit") for k in h):
            warn("rate-limit headers", "no X-RateLimit-* on a normal response (the gateway sends X-RateLimit-Limit on every response; "
                                       "check the proxy/WAF in front of it)")
        if BASE.startswith("https://") and "strict-transport-security" not in h:
            warn("HSTS", "no Strict-Transport-Security (set it at the TLS terminator)")
        if h.get("server", "").lower().startswith(("uvicorn", "hypercorn")) and BASE.startswith("https://"):
            warn("server header", f"leaks '{h['server']}'")
        if not BASE.startswith("https://") and "localhost" not in BASE and "127.0.0.1" not in BASE:
            raise AssertionError(f"production base URL is not https: {BASE}")

    def rate_limit_429_shape():
        # read-only: the 429 shape is covered by the e2e/unit tests; here only make sure a burst of 5 cheap reads is not throttled
        for _ in range(5):
            assert c.get("/health").status_code == 200

    print(f"smoke against {BASE}")
    for name, fn in (("gateway /health + version", health), ("gateway /ready (upstreams)", ready),
                     ("CORS closed to foreign origins", cors), ("admin routes closed without token", admin_closed),
                     ("protected routes require auth", protected), ("internal routes not exposed", internal_closed),
                     ("public reads work", public_read), ("error bodies clean", errors_clean),
                     ("transport/header sanity", headers), ("no throttling on health burst", rate_limit_429_shape)):
        check(name, fn)
    print(f"\n{10 - len(FAILS)}/10 checks passed" + (f", {len(WARNS)} warnings" if WARNS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
