# contract-validate / e2e extension decisions

- 2026-10-14: `scripts/contract_validate.py` runs real service processes (reusing `scripts/e2e.py` startup) instead of in-process ASGI so gateway proxying, sourcing<->trust and rfq<->payments HTTP clients are exercised exactly as in e2e. Cost: ~15 s startup.
- 2026-10-14: Validation uses `jsonschema` Draft 2020-12 + `referencing` with a retriever mapping both `file://` refs and the `$id` of common.schema.json to the local file; the OpenAPI 3.1 schemas are used as JSON Schema directly (no 3.0 `nullable`). Formats are not enforced (no format checker).
- 2026-10-14: Known drift is allowlisted with reasons rather than failing CI; each entry is classified in `docs/fixes/contract-drift.md`. Stale entries are reported so the list shrinks as drift is fixed.
- 2026-10-14: `scripts/e2e.py` now boots 12 services (adds demand 8110, payments 8111) and appends 7 steps; demand/payments steps SKIP when the admin/upstream env is unavailable (remote mode).
- 2026-10-14: Makefile is not in this task's scope; suggested follow-up: `make contract` -> `python scripts/contract_validate.py` and add pyyaml/jsonschema/referencing to `make venv`.
