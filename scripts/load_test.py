#!/usr/bin/env python3
"""Mixed-workload load test against the local mock stack (single process per service, SQLite).

    python scripts/load_test.py [--users 50] [--duration 60] [--concurrency 30]

Boots the stack like scripts/e2e.py (run it ALONE), registers synthetic users, hammers the gateway
and exits 1 on any 5xx / transport error or when any endpoint's p95 exceeds 2 s.
FF_E2E_BASE_URL=... targets an already running stack instead (no processes spawned).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
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
import e2e  # noqa: E402

P95_LIMIT_MS = 2000.0
QUERIES = ["injection molding machine", "خط انتاج معجنات", "plastic chairs", "machine", "ceramic tiles"]
ROUTES = [("Shanghai", "Baghdad"), ("Yiwu", "Erbil"), ("Shenzhen", "Basra")]
WEIGHTS = {"search": 30, "landed_cost": 15, "feed_home": 15, "rfq_create": 8, "rfq_list": 12, "tracking_list": 10, "assistant": 10}


def pct(sorted_ms: list[float], p: float) -> float:
    if not sorted_ms:
        return 0.0
    return sorted_ms[min(len(sorted_ms) - 1, int(round(p / 100 * (len(sorted_ms) - 1))))]


async def register_users(c: httpx.AsyncClient, n: int) -> list[dict[str, str]]:
    sfx = uuid.uuid4().hex[:8]
    sem = asyncio.Semaphore(10)

    async def one(i: int) -> dict[str, str]:
        async with sem:
            r = await c.post("/v1/auth/register", json={"email": f"load{i}-{sfx}@example.com", "password": "Passw0rd!x", "name": f"Load {i}"})
            r.raise_for_status()
            return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return list(await asyncio.gather(*(one(i) for i in range(n))))


async def run(users: int, duration: float, concurrency: int) -> int:
    lat: dict[str, list[float]] = {k: [] for k in WEIGHTS}
    codes: dict[str, dict[str, int]] = {k: {} for k in WEIGHTS}
    limits = httpx.Limits(max_connections=concurrency + 10, max_keepalive_connections=concurrency + 10)
    async with httpx.AsyncClient(base_url=e2e.GW, timeout=30, limits=limits) as c:
        hdrs = await register_users(c, users)
        print(f"registered {len(hdrs)} users; running {duration:.0f}s at concurrency {concurrency}")

        def make(kind: str, h: dict[str, str]):
            if kind == "search":
                return c.get("/v1/search", params={"q": random.choice(QUERIES)})
            if kind == "landed_cost":
                o, d = random.choice(ROUTES)
                return c.post("/v1/quotes/landed-cost", json={
                    "goods": {"description": "chairs", "quantity": 500, "total_value": {"amount": "5000", "currency": "USD"},
                              "total_weight_kg": 3000, "total_volume_m3": 30},
                    "origin": {"country_code": "CN", "city": o}, "destination": {"country_code": "IQ", "city": d}, "display_currency": "USD"})
            if kind == "feed_home":
                return c.get("/v1/feed/home", headers=h)
            if kind == "rfq_create":
                return c.post("/v1/requests", headers=h, json={
                    "kind": "product", "title": f"Load chairs {random.randint(1, 9999)}", "quantity": 500, "unit": "piece",
                    "target_price": {"amount": "8", "currency": "USD"}, "destination": {"country_code": "IQ", "city": "Erbil"}})
            if kind == "rfq_list":
                return c.get("/v1/requests", params={"scope": "mine"}, headers=h)
            if kind == "tracking_list":
                return c.get("/v1/shipments", headers=h)
            return c.post("/v1/assistant/query", headers=h, json={"text": "ابي ٥٠٠ كرسي بلاستك من الصين الى اربيل", "locale": "ar"})

        kinds, weights = list(WEIGHTS), list(WEIGHTS.values())
        end = time.perf_counter() + duration

        async def worker(idx: int) -> None:
            rnd = random.Random(idx)
            while time.perf_counter() < end:
                kind = rnd.choices(kinds, weights)[0]
                h = hdrs[rnd.randrange(len(hdrs))]
                t0 = time.perf_counter()
                try:
                    code = str((await make(kind, h)).status_code)
                except httpx.HTTPError as e:
                    code = type(e).__name__
                lat[kind].append((time.perf_counter() - t0) * 1000)
                codes[kind][code] = codes[kind].get(code, 0) + 1

        t_start = time.perf_counter()
        await asyncio.gather(*(worker(i) for i in range(concurrency)))
        elapsed = time.perf_counter() - t_start

    bad = False
    print(f"\n{'endpoint':<14}{'n':>7}{'rps':>8}{'p50':>8}{'p95':>8}{'p99':>8}{'max':>8}{'5xx/exc':>9}{'4xx':>6}  err%")
    total = 0
    for k in WEIGHTS:
        s = sorted(lat[k])
        n = len(s)
        total += n
        c5 = sum(v for code, v in codes[k].items() if not code.isdigit() or code.startswith("5"))
        c4 = sum(v for code, v in codes[k].items() if code.startswith("4"))
        p95 = pct(s, 95)
        flag = ""
        if c5 or p95 > P95_LIMIT_MS:
            bad = True
            flag = "  FAIL"
        print(f"{k:<14}{n:>7}{n / elapsed:>8.1f}{statistics.median(s) if s else 0:>8.1f}{p95:>8.1f}{pct(s, 99):>8.1f}{(s[-1] if s else 0):>8.1f}{c5:>9}{c4:>6}  {100 * (c5 + c4) / max(n, 1):.2f}{flag}")
        if c4 or c5:
            print(f"    status counts: {codes[k]}")
    print(f"total {total} requests in {elapsed:.1f}s = {total / elapsed:.1f} req/s (mock adapters, SQLite, one process per service)")
    return 1 if bad or not total else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--concurrency", type=int, default=30)
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="ff-load-"))
    procs: list[subprocess.Popen] = []
    try:
        if e2e.REMOTE:
            for _ in range(60):
                try:
                    if httpx.get(f"{e2e.GW}/health", timeout=3).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(1)
        else:
            os.environ.setdefault("FF_GATEWAY_REGISTER_PER_HOUR", "100000")  # per-IP signup cap would reject the synthetic users
            procs = e2e.start_services(tmp)
            e2e.wait_health(tmp)
        return asyncio.run(run(a.users, a.duration, a.concurrency))
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        for log in sorted(tmp.glob("*.log")):
            t = log.read_text(errors="replace")
            if "Traceback" in t:
                print(f"--- {log.name} (tail)\n{t[-1500:]}")
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
