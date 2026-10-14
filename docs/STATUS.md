# Status — 2026-10-14 evening (architect)

**Goal:** Phases 0–3 on mock adapters (done), now hardening before Phase 4 (real data).

## Done
- 10 backend services (gateway, sourcing, logistics, geo, trust, rfq, messaging, tracking, notifications, assistant); all tests + ruff green; `scripts/e2e.py` 22/22 through the gateway.
- Flutter app (ar/en, RTL): discover, listing, supplier, landed-cost calculator, FX, carriers, requests/offers, chat (REST + WebSocket), tracking, assistant, profile, supplier-claim. CI builds a debug APK.
- Security review done: refresh-token rotation, supplier claims need admin approval, CORS off by default, only gateway port published in compose.
- Data: 165 listings / 83 suppliers (mock), 66 countries, ~200 hubs, 41 duty countries, 25 carriers, extended sea graph.

## Added since the first snapshot
- 11 services now (+demand, payments); admin console (apps/admin); WebSocket chat via gateway; Alembic/Postgres support; structured logs + /ready.
- Search: bilingual synonyms, typo tolerance, ranking, facets; HS code finder (~690 indicative codes, verify with a customs broker).
- Mobile: onboarding, persistence, watchlist/alerts, compare, saved searches, trust v2 UI, notification prefs, 120+ tests incl. widget smoke tests.
- Notifications delivery adapters (push/email, off by default); payments (mock + USDT skeleton, ledger, signed webhooks).

- 13 services now (+media). Suppliers can publish their own listings (native source), upload images, verify digest email. Contract validation (132 responses, 0 drift) and e2e (31 steps) in CI.
- Gateway: public image GETs have their own rate bucket (media_rate_limit_per_minute).

## Next (needs owner input)
- Phase 4: official supplier API account (Alibaba or licensed provider) and a freight-rate provider; until then all data is mock.
- Real-device test of the APK (Flutter never compiled locally; CI is the only check).

## Known gaps
- Rate limiting is per-IP in-memory; direct service ports trust X-User-Id when FF_INTERNAL_TOKEN is unset (private network only).
- Duty and freight tables are approximations; some hub coordinates unverified; some sea regions missing (see docs/requests/data-geo-sea-nodes.md).
- Admin approval of supplier claims has no UI (HTTP endpoints only).
