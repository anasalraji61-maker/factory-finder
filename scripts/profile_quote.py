#!/usr/bin/env python3
# ruff: noqa: E701, E702
"""cProfile the landed-cost engine in-process (mock geo/fx). Usage: python scripts/profile_quote.py [profile]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services/logistics/src"))
import asyncio
import cProfile
import pstats
import statistics
import time

from ff_logistics.adapters.fx import FxService, MockFx
from ff_logistics.clients.geo import MockGeo
from ff_logistics.domain.engine import Engine
from ff_logistics.schemas import LandedCostRequest


class CountGeo(MockGeo):
    n = 0
    async def resolve_city(self,*a): CountGeo.n+=1; return await super().resolve_city(*a)
    async def hubs(self,*a,**k): CountGeo.n+=1; return await super().hubs(*a,**k)
    async def nearest_hubs(self,*a,**k): CountGeo.n+=1; return await super().nearest_hubs(*a,**k)
    async def distance_km(self,*a,**k): CountGeo.n+=1; return await super().distance_km(*a,**k)
body={"goods":{"description":"chairs","quantity":500,"total_value":{"amount":"5000","currency":"USD"},"total_weight_kg":3000,"total_volume_m3":30},
 "origin":{"country_code":"CN","city":"Shanghai"},"destination":{"country_code":"IQ","city":"Baghdad"},"display_currency":"USD"}
async def one(geo=None):
    return await Engine(geo or CountGeo(), FxService(MockFx())).quote(LandedCostRequest(**body))
async def main():
    await one()
    CountGeo.n=0; await one(); print("geo calls/quote", CountGeo.n)
    ts=[]
    for _ in range(100):
        t=time.perf_counter(); await one(); ts.append((time.perf_counter()-t)*1000)
    print("p50 ms", statistics.median(ts))
    if len(sys.argv)>1:
        pr=cProfile.Profile(); pr.enable()
        for _ in range(100): await one()
        pr.disable(); pstats.Stats(pr).sort_stats("cumtime").print_stats(22)
asyncio.run(main())
