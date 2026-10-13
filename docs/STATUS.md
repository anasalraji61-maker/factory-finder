# Status — 2026-10-14 (architect)

**Goal:** Phases 0–3 on mock adapters (done), now hardening before Phase 4 (real data).

## Done
- 10 backend services (gateway, sourcing, logistics, geo, trust, rfq, messaging, tracking, notifications, assistant); all tests + ruff green; `scripts/e2e.py` 22/22 through the gateway.
- Flutter app (ar/en, RTL): discover, listing, supplier, landed-cost calculator, FX, carriers, requests/offers, chat (REST + WebSocket), tracking, assistant, profile, supplier-claim. CI builds a debug APK.
- Security review done: refresh-token rotation, supplier claims need admin approval, CORS off by default, only gateway port published in compose.
- Data: 165 listings / 83 suppliers (mock), 66 countries, ~200 hubs, 41 duty countries, 25 carriers, extended sea graph.

## Next (needs owner input)
- Phase 4: official supplier API account (Alibaba or licensed provider) and a freight-rate provider; until then all data is mock.
- Real-device test of the APK (Flutter never compiled locally; CI is the only check).

## Known gaps
- Rate limiting is per-IP in-memory; direct service ports trust X-User-Id when FF_INTERNAL_TOKEN is unset (private network only).
- Duty and freight tables are approximations; some hub coordinates unverified; some sea regions missing (see docs/requests/data-geo-sea-nodes.md).
- Admin approval of supplier claims has no UI (HTTP endpoints only).
