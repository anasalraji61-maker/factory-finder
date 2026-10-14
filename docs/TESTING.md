# Testing

All commands run from the repo root with the repo venv (`make venv` creates `.venv`; contract validation also needs
`pip install pyyaml jsonschema referencing`). No test touches the network beyond localhost.

## 1. Unit / service tests (mocks only)

```
make test                 # every service: cd services/<svc> && pytest -q
make test-<svc>           # one service, e.g. make test-rfq
make lint                 # ruff over services and scripts
```

## 2. Route check (code vs contract paths)

```
python scripts/contract_check.py [service ...]
```
Compares method+path sets of each FastAPI app with `contracts/openapi/<svc>.yaml`. Fast, no processes.

## 3. Contract validation (response bodies vs schemas)

```
python scripts/contract_validate.py        # add -v to list every validated call
```
Boots the 12 services as local processes (temp SQLite, mock providers, same startup as e2e), calls representative
endpoints of every service (plus gateway auth/me/home/admin and a few gateway-proxied routes) and validates each JSON
body against the OpenAPI response schema with full `$ref` resolution (`#/components/...` and
`../schemas/common.schema.json`). Output lines: `DRIFT` (fails the run, with service, method, contract path, status,
JSON path of the offending value and the schema location), `ALLOW` (matched by `scripts/contract_validate.allow.json`),
`STALE` (allowlist entry that matches nothing: delete it). Exit code is 1 on any non-allowlisted drift.

Allowlist entries need a `reason`; keys: `spec`, `method` (`*` = any), `path` (contract template, `*` = any), optional
`status`, `location` (regex on the JSON path), `message_contains`. Classification of the current entries is in
`docs/fixes/contract-drift.md`. Prefer fixing the contract/service and removing the entry.

## 4. End-to-end scenario

```
python scripts/e2e.py                                  # boots 12 services locally, runs all steps via the gateway
FF_E2E_BASE_URL=http://localhost:8000 python scripts/e2e.py   # against a running stack (make compose-e2e)
```
Locally the script configures a test admin token (`FF_E2E_ADMIN_TOKEN`, default `e2e-admin-token`) for the gateway and
payments, the mock payment provider, the demand kill-switch on and mock sourcing for demand. Against a remote stack the
demand/payments steps print `SKIP` (not a failure) when the admin route is not available (set `FF_E2E_ADMIN_TOKEN` to the
stack's `FF_GATEWAY_ADMIN_TOKEN` to run the demand step) or the upstream is unreachable. Steps that need direct service
ports (X-User-Id injection) are skipped in remote mode.

## 5. Extended end-to-end flows and production smoke

```
python scripts/e2e_extended.py        # or: make e2e-extended  (boots 12+1 local services, ~30 s)
FF_E2E_BASE_URL=https://stack python scripts/smoke_prod.py   # or: make smoke
```
`e2e_extended.py` covers what `e2e.py` does not: listing moderation (2 reports -> `pending_review` -> admin hide ->
restore through `/v1/admin/moderation/*`), messaging media attachments, email verification (in-process gateway with the
mock mailer, because the outbox is not reachable over HTTP), tracking outbox -> relay -> notifications alert (a row is
inserted into the local tracking SQLite file), deals list as buyer/supplier, assistant cards and the daily quota,
reviews on a completed deal, compliance endpoints (SKIP while none exist) and the `FF_ENV=production` fail-closed guard
(one subprocess per service). Steps are independent; a failed setup only skips its dependants. With `FF_E2E_BASE_URL`
the steps that need local processes, databases or env are skipped.

`smoke_prod.py` is a read-only post-deploy check (GET/OPTIONS only, no accounts): gateway `/health` + version, `/ready`
with every upstream, CORS closed for foreign origins, admin routes 401/404 without a token, protected and internal
routes closed, error bodies without traces, https/HSTS and rate-limit header sanity (warnings only). Exit 1 on any FAIL.

## CI

`.github/workflows/e2e.yml` runs route check, contract validation and the e2e scenario on every change to services,
contracts or scripts; `backend.yml` runs the unit tests. The e2e workflow also runs `scripts/e2e_extended.py`.
