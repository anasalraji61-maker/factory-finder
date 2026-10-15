# Developer guide

Read `CLAUDE.md` first (it wins on any conflict), then `docs/ARCHITECTURE.md` and your brief in `docs/AGENTS.md`.
Related: `docs/TESTING.md` (all test tiers), `docs/API_EXAMPLES.md` (curl through the gateway), `docs/OPS.md`, `docs/DEPLOY.md`.

## 1. Run the stack locally

```
make venv                 # creates .venv with every dependency used by the services and scripts
make dev                  # docker compose up --build; only the gateway publishes a port (http://localhost:8000)
make down
```
Without Docker, boot all services as local processes with a temp SQLite DB, mock providers and test secrets:
```
python scripts/serve_stack.py                       # gateway on :8000, prints READY once healthy and seeded
FF_STACK_PORT=18000 FF_STACK_INFO=/tmp/ff_stack.json python scripts/serve_stack.py   # second stack, every port shifted by +10000
```
Or run one service: `cd services/<svc> && ../../.venv/bin/uvicorn ff_<svc>.main:app --port <port>`.
Ports: gateway 8000, sourcing 8101, logistics 8102, geo 8103, trust 8104, rfq 8105, messaging 8106, tracking 8107,
notifications 8108, assistant 8109, demand 8110, payments 8111, media 8112, feed 8113, freight 8114.
Configuration is environment only (`FF_<SERVICE>_*`); copy `.env.example`, never commit values. Empty admin tokens
disable the `/v1/admin/*` routes (404). `FF_ENV=production` makes services refuse to start without their secrets.

## 2. Repo conventions

- **Contracts first.** The OpenAPI file in `contracts/openapi/<svc>.yaml` (and `contracts/schemas/`) exists before the
  endpoint does. Changes to existing contracts are additive (new optional fields); breaking changes need `/v2`.
- **Lanes.** Edit only the directory your brief assigns. Need something elsewhere? Write `docs/requests/<module>-<topic>.md`
  and continue against a mock. Never import another module's internals; talk through contracts and HTTP clients.
- **Adapters everywhere** (suppliers, freight rates, FX, tracking, LLM, payments): interface + real adapter + deterministic mock. Tests use mocks only; no network.
- **Money** is `Decimal` strings in JSON; every cost line carries currency, source, timestamp; estimates carry a range.
- **UI strings** go through i18n (Arabic first, English second).
- **Secrets** never enter the repo (it is public). Keys come from env vars only; never print or log them.
- **Decisions** go in `docs/decisions/<agent-id>.md` (one line: date, decision, why).
- Agents do not run git; the orchestrator commits (`<module>: <what>`).
- Every change adds or updates tests, the module README and, for env vars, the README env table.

## 3. Adding an adapter (mock + real)

Common pattern: (1) interface/base class, (2) `mock` adapter that is deterministic and is the fallback, (3) real adapter that is
**off by default**, reads its key from an env var name (never a literal), and degrades to the mock/tables on any failure,
(4) register it, (5) tests against the mock plus recorded fixtures for the real one (`respx`, no network).

### Supplier source (`services/sourcing/src/ff_sourcing/adapters/`)
1. Subclass `SourceAdapter` (`base.py`): set `id`, `name`, `mode` (`mock | official_api | licensed_feed`), `compliance` (ToS note);
   implement `search`, `get_listing`, `get_supplier`, `health`; override `configured()` when a key is needed.
2. Prefer building on `http_provider.py` (`ProviderConfig` + `HttpProviderAdapter`, see `alibaba_openapi.py`) or the JSON-mapped
   `licensed_rest.py`; page-reading adapters build on `http_base.py` (rate limit, robots.txt, cache, honest User-Agent).
3. Add it to `build_registry()` in `registry.py`; enable with `FF_SOURCING_ENABLED_SOURCES` (default `mock,native`).
4. Extend `contracts/openapi/sourcing.yaml` only additively (e.g. a new `source` value). Tests live in `services/sourcing/tests`.

### Freight rate provider (`services/logistics/src/ff_logistics/adapters/freight.py`)
Implement `FreightRateProvider.quote(FreightRequest) -> FreightQuote | None`. `None` means "use the built-in tables" (what `MockFreight`
returns). Raise `FreightUnavailable` on any failure so the engine falls back. Return low/high so the engine can show a range;
the result is always an estimate. Same pattern for FX (`fx.py`) and carriers (`carriers.py`). Kill switch: `FF_LOGISTICS_KILL_SWITCH`.

### Tracking provider (`services/tracking/src/ff_tracking/adapters/`)
Implement the `TrackingProvider` protocol (`base.py`): `async track(reference, reference_type, carrier, *, anchor, now) -> TrackingSnapshot`.
Raise `ProviderUnavailable(reason=...)` (stable codes: kill_switch, not_configured, blocked, rate_limited, upstream_error, timeout,
bad_payload, cooldown, unsupported). `mock.py` fabricates data from `anchor`; `router.py` (`RoutingProvider`) picks container /
AWB / vessel-ETA providers and falls back to the mock with a warning. Official or licensed APIs only for AIS/vessel data.

### Lawful-use checklist (CLAUDE.md rule 6; every real adapter)
- [ ] Official API or licensed data provider preferred; page reading only where the terms allow it.
- [ ] Respects `robots.txt` and the site's terms; never bypasses CAPTCHA, login or paywall.
- [ ] Rate limit of at least 3 s between requests per host; aggressive caching (TTL).
- [ ] Honest User-Agent identifying the platform.
- [ ] Off by default and switchable off by config (per-adapter flag plus the module kill switch).
- [ ] Key/token read from an env var, never printed, logged or committed.
- [ ] Any failure falls back to the mock/tables; result labelled with source and timestamp; estimates labelled.
- [ ] Tests use the mock and recorded fixtures; unverified endpoint shapes are documented as UNVERIFIED in the module README.
- [ ] Social platforms: no automated private messages to strangers; public drafts only, low volume, human approval (rule 7).

## 4. Adding a service

1. Contract: `contracts/openapi/<svc>.yaml` (health + ready + routes + error shape), additive schemas under `contracts/schemas/`.
2. Create `services/<svc>/` with `pyproject.toml`, `src/ff_<svc>/main.py` (FastAPI `app`, `/health`, `/ready`), `tests/`, `README.md`
   (what it does, how to run, env vars). Settings use the `FF_<SVC>_` prefix; own DB via `FF_<SVC>_DATABASE_URL` (+ Alembic migrations).
3. Wire-up (orchestrator / gateway owner): add the name to `SERVICES` in the `Makefile`, to `SERVICES` in `scripts/e2e.py`
   (name, port, module), `docker-compose.yml`, the gateway prefix table (`services/gateway/src/ff_gateway/domain/routing.py`) and the
   backend CI matrix. Only the gateway may be published; user identity arrives as `X-User-Id` plus `X-Internal-Token`.
4. Add `/v1/internal/users/{user_id}/export` and `/data` if the service stores personal data (account export/deletion).
5. Run `python scripts/contract_check.py <svc>` and `python scripts/contract_validate.py`; add a step to an e2e script.

## 5. Tests and e2e

```
make test | make test-<svc>        # unit/service tests, mocks only
make lint                          # ruff over services and scripts
python scripts/contract_check.py   # code routes vs contract paths
python scripts/contract_validate.py  # response bodies vs schemas; allowlist: scripts/contract_validate.allow.json
make e2e                           # scripts/e2e.py: boots the stack locally, scenario through the gateway
make e2e-extended                  # moderation, media, email verify, tracking relay, deals, assistant quota, freight, ...
make e2e-scenarios                 # five focused edge scenarios
make compose-e2e                   # docker compose up, run e2e against http://localhost:8000, tear down
FF_E2E_BASE_URL=https://api.example.com make smoke   # read-only post-deploy checks
```
`pip install pyyaml jsonschema referencing` is needed for the contract scripts. The e2e harnesses use well-known test secrets and refuse
to run with `FF_ENV=production|prod|staging`.

**Port-collision rule.** The local e2e scripts (`e2e.py`, `e2e_extended.py`, `e2e_scenarios.py`, `contract_validate.py`) bind the fixed ports
8000 and 8101-8114. Never run two of them at once, and stop `make dev` / `serve_stack.py` first, or the second run talks to the first one's
processes. To run side by side, use `serve_stack.py` with `FF_STACK_PORT` (all ports shift by the same offset). Local runs use temp
SQLite files and clean up after themselves; a stale uvicorn from a killed run is the usual cause of odd failures (check `lsof -i :8000`).

## 6. CI (`.github/workflows/`)

| Workflow | What it runs |
|---|---|
| `backend.yml` | per service (matrix): install via `scripts/install_service.py`, `ruff check`, `pytest`; plus `packages/py-common` |
| `e2e.yml` | `contract_check.py`, `contract_validate.py`, `e2e.py`, `e2e_extended.py`, `e2e_scenarios.py` |
| `mobile.yml` / `ios.yml` | Flutter analyze + tests (Android / iOS build) |
| `mobile-live.yml` | boots `serve_stack.py` and runs the app's live-contract tests against it |
| `audit.yml` | dependency vulnerability scan (non-fatal locally via `make audit`) |

`make test`, `make lint` and the e2e scripts must pass before a phase is closed.

## 7. Common pitfalls (from `docs/fixes/`)

- **Contract drift** (`contract-drift.md`): nullable optional fields need `type: [string, "null"]`; `allOf` with `additionalProperties: false`
  rejects everything; `POST /v1/auth/refresh` returns tokens only (no `user`). Prefer fixing the contract over growing the allowlist.
- **Gateway-only access.** `/v1/internal/*`, `/v1/media/admin/*` and `POST /v1/alerts/evaluate|digest` are never reachable through the gateway;
  e2e hits those on the direct service port, so those steps are skipped in remote mode. `/v1/admin/*` needs `X-Admin-Token` and is 404 when unset.
- **Ownership answers** differ by service: messaging/notifications answer 403 for another user's id, freight/feed/rfq mostly 403 or 404. Assert on `in (403, 404)` where the contract allows both.
- **Hidden content must 404 everywhere** (feed unlike on hidden posts was a bug); apply moderation state on every read and write path.
- **Check-then-insert races** (concurrent duplicate invoices, media quota): use unique constraints / per-owner serialisation, and return the existing row on idempotent creates.
- **Untrusted downstream strings** in the assistant must pass the sanitiser before reaching answers or cards.
- **Estimates must be labelled** (as_of, source, range, duty-table confidence); sum of lines equals the midpoint of `total` (see `logistics-accuracy-review-2026-10.md`).
- **Per-process state** (WebSocket hub, typing throttle, media quota lock, random media signing key) is a multi-replica limitation; set `FF_MEDIA_SIGNING_KEY` outside dev.
- **Deploy hygiene:** compose secrets default to empty; set `FF_ENV=production` plus JWT secret and internal token (`supply-chain-review-2026-10.md`).
- Rate limits are tight in prod; the harnesses raise them (`FF_GATEWAY_RATE_LIMIT_PER_MINUTE`) for local runs only.
