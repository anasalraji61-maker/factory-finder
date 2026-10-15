# logistics decisions
- 2026-10-13 | Total range is symmetric around the sum of lines (min=sum-spread, max=sum+spread; per-stage spreads 10-25%) | keeps `total == sum(lines)` exact while still giving a range.
- 2026-10-13 | Recommended = lowest 0.6*cost_norm + 0.4*time_norm over options (logistics cost, mid transit days, min-max normalised) | simple, explainable cost/time trade-off; ties go to cheaper.
- 2026-10-13 | `goods` is a cost line (stage `goods`) so totals are landed cost, not freight only; options sort by logistics cost (same order).
- 2026-10-13 | FCL/rail only offered by default above size thresholds (20': 8 m3 or 5 t; 40': 20 m3 or 20 t; 40HC: >58 m3; rail: 8 m3 or 5 t); an explicit `modes` filter bypasses them | avoids absurd options for small cargo.
- 2026-10-13 | Customs value = goods price + buyer-paid pre-import freight/insurance per incoterm (EXW/FCA/FOB add freight; CFR adds insurance; CIF/DAP/DDP add none) | CIF-basis valuation.
- 2026-10-13 | Quote-level `warnings` and option-level `warnings` added as additive fields; geo outage maps to 502 `geo_unavailable`; unknown city falls back to a default city of the country.
- 2026-10-13 | Umm Qasr carries a congestion/war-risk surcharge in routes.json so Mersin+truck wins for far-north Iraq (Erbil); values approximate.
- 2026-10-13 | geo client parses geo responses tolerantly (list or {items}; lat/lon or point) since geo's contract was not final; hub ids in routes.json are UN/LOCODE and skipped gracefully if geo lacks them.
2026-10-15: freight_override carries optional mode_family and the freight helper lives at /v1/freight/quotes/{id}/landed-cost-input (service prefix); the client relays it, no service-to-service call. Why: a forwarder quote is for one mode, and rule 1 forbids coupling.
