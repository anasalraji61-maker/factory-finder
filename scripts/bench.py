#!/usr/bin/env python3
"""Informational latency benchmark (p50/p95) for key gateway paths with mock data. Always exits 0.

    python scripts/bench.py                       # boots the stack like scripts/e2e.py (localhost only)
    FF_E2E_BASE_URL=http://localhost:8000 python scripts/bench.py   # against a running stack
    FF_BENCH_N=100 python scripts/bench.py        # iterations per path (default 50)

Note: services are separate processes (as in e2e), so numbers include gateway -> service hops.
"""
from __future__ import annotations

import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e  # noqa: E402  (reuses service boot helpers; importing has no side effects)

N = int(os.environ.get("FF_BENCH_N", "50"))
WARMUP = 3
GW = e2e.GW
QUOTE = {
    "goods": {"description": "chairs", "quantity": 500, "total_value": {"amount": "5000", "currency": "USD"},
              "total_weight_kg": 3000, "total_volume_m3": 30},
    "origin": {"country_code": "CN", "city": "Shanghai"}, "destination": {"country_code": "IQ", "city": "Baghdad"},
    "display_currency": "USD",
}


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, round(p / 100 * (len(s) - 1)))]


def measure(c: httpx.Client, name: str, call, rows: list) -> None:
    lat: list[float] = []
    bad = 0
    try:
        for i in range(WARMUP + N):
            t = time.perf_counter()
            r = call()
            dt = (time.perf_counter() - t) * 1000
            if r.status_code >= 400:
                bad += 1
            if i >= WARMUP:
                lat.append(dt)
    except Exception as e:  # noqa: BLE001
        rows.append((name, "-", "-", "-", f"error {type(e).__name__}"))
        return
    rows.append((name, f"{pct(lat, 50):.1f}", f"{pct(lat, 95):.1f}", f"{statistics.mean(lat):.1f}",
                 f"{bad} non-2xx" if bad else "ok"))


def run() -> list:
    c = httpx.Client(base_url=GW, timeout=30)
    rows: list = []
    sfx = uuid.uuid4().hex[:8]
    d = c.post("/v1/auth/register", json={"email": f"bench{sfx}@example.com", "password": "Passw0rd!x", "name": "Bench"}).json()
    h = {"Authorization": f"Bearer {d['access_token']}"}
    c.patch("/v1/me", headers=h, json={"role": "buyer"})
    lst = c.get("/v1/search", params={"q": "injection molding machine"}).json()
    its = lst if isinstance(lst, list) else lst.get("items") or lst.get("results") or []
    lid, sid = its[0]["id"], its[0]["supplier"]["id"]
    req = c.post("/v1/requests", headers=h, json={
        "kind": "product", "title": "bench", "quantity": 10, "unit": "piece",
        "target_price": {"amount": "8", "currency": "USD"}, "destination": {"country_code": "IQ", "city": "Erbil"}})
    rid = req.json().get("id") if req.status_code < 300 else None
    measure(c, "search (q=injection molding machine)", lambda: c.get("/v1/search", params={"q": "injection molding machine"}), rows)
    measure(c, "search (Arabic, sort=price_asc)", lambda: c.get("/v1/search", params={"q": "خط انتاج معجنات", "sort": "price_asc"}), rows)
    measure(c, "landed-cost quote", lambda: c.post("/v1/quotes/landed-cost", json=QUOTE), rows)
    measure(c, "trust score", lambda: c.get(f"/v1/trust/suppliers/{sid}", headers=h), rows)
    measure(c, "listing detail", lambda: c.get(f"/v1/listings/{lid}"), rows)
    measure(c, "deals list", lambda: c.get("/v1/deals", headers=h), rows)
    measure(c, "requests list (mine)", lambda: c.get("/v1/requests", headers=h), rows)
    if rid:
        measure(c, "request offers list", lambda: c.get(f"/v1/requests/{rid}/offers", headers=h), rows)
    measure(c, "notifications inbox (/v1/alerts)", lambda: c.get("/v1/alerts", headers=h), rows)
    return rows


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ff-bench-"))
    procs: list[subprocess.Popen] = []
    rows: list = []
    try:
        if e2e.REMOTE:
            for _ in range(60):
                try:
                    if httpx.get(f"{GW}/health", timeout=3).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(1)
        else:
            procs = e2e.start_services(tmp)
            e2e.wait_health(tmp)
        rows = run()
    except BaseException as e:  # noqa: BLE001  (informational: never fail)
        print(f"bench aborted: {type(e).__name__}: {e}")
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    if rows:
        print(f"\n{'path':<40}{'p50 ms':>9}{'p95 ms':>9}{'mean ms':>9}  status   (n={N})")
        for r in rows:
            print(f"{r[0]:<40}{r[1]:>9}{r[2]:>9}{r[3]:>9}  {r[4]}")
    return 0


if __name__ == "__main__":
    main()
    sys.exit(0)
