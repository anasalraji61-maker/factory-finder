2026-10-14 | Real providers are skeletons (container/B-L, AWB, AIS vessel ETA) with UNVERIFIED wire shapes, fixture-tested only, `FF_TRACKING_PROVIDER=http` opt-in | no live licensed API available; mirrors sourcing http_provider / logistics freight
2026-10-14 | On provider failure fall back to mock with `warning=provider_unavailable:<reason>`; never overwrite real events with mock data | graceful UX without silently fabricating over real data; `FALLBACK_TO_MOCK=false` gives 502
2026-10-14 | Provider gate-out maps to status `out_for_delivery` and a `gate_out` milestone; no new enum value | status enum is a published contract
2026-10-14 | Arrival/discharge at a hub other than the known destination hub is normalized to `transshipment` | providers rarely label transshipment consistently
2026-10-14 | Stale ETA (past, not landed) is recomputed as now+24 h and flagged delayed; delayed = slip > 12 h vs first ETA | simple, explainable heuristic
2026-10-14 | Notification events go to a `tracking_outbox` table (unique dedupe_key, written after the shipment save); notifications pulls it later (docs/requests/tracking-notify.md) | module boundary: tracking does not call notifications
2026-10-14 | Refresh job is an in-process asyncio loop, off by default, per-shipment min interval N hours (default 6) | no extra infra; single-instance assumption documented
2026-10-14 | Added 10 ocean lines and 23 airlines to carrier tables (best effort, verify owner codes against the BIC registry) | carrier detection coverage
