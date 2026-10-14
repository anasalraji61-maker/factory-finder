# demand (port 8110, internal only)

Phase 5 demand matching with a **human in the loop** (CLAUDE.md rule 7). Contract: `contracts/openapi/demand.yaml`.

- Detects PUBLIC buy-requests and prepares matched offers as **draft public replies**. It never posts anything, never sends private messages, and does no scraping.
- Input: `POST /v1/signals` (a human pastes a public post's text/URL; the URL is never fetched) or `POST /v1/signals/poll` through a `SignalSource` adapter (`signals.py`; only a deterministic mock with Arabic/English fixtures ships; real sources must use official APIs and be switchable off).
- Pipeline: dedupe (URL or normalized text) -> language detection (ar/en) -> keyword intent (`intent.py`) -> sourcing search (`sourcing.py`: Protocol + httpx + mock) -> draft in the post's language with an honest platform disclosure and indicative listing prices only.
- Drafts: `draft -> approved -> published`, `draft|approved -> rejected`. `approve` and `mark-published` need the kill-switch ON (else 403) and `approve` enforces the daily cap (429) at approval time (UTC day). Every transition is in the draft's audit log (actor, time). `outcome` tracks replied / converted / no_response.
- Admin only: `X-User-Id` required, `X-Internal-Token` when `FF_INTERNAL_TOKEN` is set. No gateway route yet (see `docs/requests/demand-gateway.md`).

Run: `uvicorn ff_demand.main:app --port 8110` (from `src/`). Test: `../../.venv/bin/python -m pytest -q`.

Env (prefix `FF_DEMAND_`): `ENABLED` (default **false**, kill-switch), `DAILY_CAP` (20), `DATABASE_URL`, `SOURCING_BASE_URL`, `USE_MOCK_SOURCING`, `MAX_CANDIDATES`, `SIGNAL_SOURCE` (mock); shared `FF_INTERNAL_TOKEN`.
