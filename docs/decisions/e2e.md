# e2e decisions / bugs found

- 2026-10-13: `scripts/e2e.py` boots all 10 services (uvicorn, temp sqlite, mock FX, trust over http) and runs 22 steps through the gateway; CI in `.github/workflows/e2e.yml`.
- Result: 22/22 pass. Integration wiring (gateway prefixes, header propagation, sourcing<->trust, logistics<->geo, assistant orchestration, rfq/messaging/tracking/notifications ownership via X-User-Id) needed no fixes.
- Bug fixed (assistant): "ابي ٥٠٠ كرسي بلاستك من الصين الى اربيل" parsed to query "plastic chair"; sourcing ANDs terms and the catalog has no plastic chair, so the assistant answered "no results" and gave no quote. `services/assistant/src/ff_assistant/service.py::_search_listings` now retries with the head noun (last word) when a multi-word query returns nothing.
- Notes (by design, not bugs): `/v1/fx/convert` and `/v1/trust/*` require a bearer token at the gateway (only `fx/rates` and `quotes/landed-cost` are public); register has no `role` field (set via PATCH /v1/me); landed-cost `total` is a {min,max} range and lines sum to its midpoint.
- Script gotchas found while writing: the first draft's trust-band check passed vacuously on an empty result list; fields are `supplier.trust_band`/`trust_score` (flat), not nested.
