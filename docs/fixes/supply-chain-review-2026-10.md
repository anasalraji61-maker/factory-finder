# Supply-chain / infra review — 2026-10-15

Scope: infra, compose, workflows, `.env.example`, pyproject dependency declarations. No service source touched.

## 1. Secret scan (working tree, `.venv`/`.git` excluded)
- No private keys, `sk-`, `AKIA`, `ghp_`, `xox*`, `AIza*` or long base64 blobs. No `.env`/key/keystore/google-services files tracked; `.gitignore` ignores `.env*` except `.env.example`; `.env.example` has only empty values.
- Only key-like literals: test/e2e fixtures (`scripts/e2e.py`: `e2e-admin-token`, `e2e-webhook-secret`, `test-secret`) and mobile fixture sigs (`sig=0123abcd`). `scripts/e2e.py` refuses to run with `FF_ENV` set to production/unset, so they are not prod defaults.
- docker-compose: every token/secret defaults to empty (`${VAR:-}`), which disables admin routes (404). No default admin token anywhere. `FF_POSTGRES_PASSWORD` empty makes postgres refuse to start (safe).
- Residual risks (not changed, service code): an empty `FF_GATEWAY_JWT_SECRET` / `FF_INTERNAL_TOKEN` in non-production must be rejected in production (`FF_ENV=production` guard exists; keep it). Compose `FF_ENV` defaults empty — set `FF_ENV=production` in any real deploy.

## 2. Dependency audit (pip-audit 2.10.1)
- Installed `.venv`: no known vulnerabilities.
- Declared deps are floors only (`>=`, no upper pins), so the floor itself was audited. Vulnerable floors found and raised (minimum versions with fixes; installed versions already newer):
  - `pillow>=10.3` -> `>=12.3` (media; ~11 advisories, fixed 12.3.0)
  - `python-multipart>=0.0.9` -> `>=0.0.31` (media; 9 advisories)
  - `pyjwt>=2.8` -> `>=2.15` (gateway; 4 advisories)
  - `cryptography>=42` -> `>=49` (notifications `fcm` extra; ~14 advisories)
- Other floors (fastapi, pydantic, httpx, uvicorn, sqlalchemy, bcrypt, websockets, redis, asyncpg, alembic, pyyaml, jsonschema) had no findings.
- Recommendation: add a lock/constraints file (`pip-compile --generate-hashes`) and use it in the Dockerfile; builds currently resolve latest at build time. Add `pip-audit` as a scheduled CI job.
- Tests: media, gateway, notifications suites pass (media showed one transient `test_path_tricks_are_refused` error on a concurrent first run; passes on rerun — likely a shared `media-data` dir race, worth a look by the media owner).

## 3. Docker hardening (applied)
- Dockerfile: base pinned to `python:3.12-slim-bookworm` (was floating `slim`); fixed uid/gid 10001 non-root with nologin shell; `PYTHONDONTWRITEBYTECODE`, pip cache off; installer script removed from image; nothing secret baked (env at runtime only).
- Compose: shared `x-hardening` anchor on all 15 services: `cap_drop: ALL`, `no-new-privileges`, `init`, `pids_limit`, `mem_limit 512m` (media 1g), `cpus 1.0`, bounded json logs. Stateless `geo`, `logistics`, `assistant` are `read_only` with `/tmp` tmpfs (verified no disk writes in their source). Postgres gets no-new-privileges + limits.
- Already good: only the gateway publishes a port (8000); others `expose`; healthchecks everywhere; `depends_on: service_healthy`.
- Not done / follow-ups: (a) pin images by digest (`python:3.12-slim-bookworm@sha256:...`, `postgres:16-alpine`) — needs registry access; (b) `read_only` for DB services requires moving default SQLite files to a volume (they write `./*.db` in `/app`); for production use PostgreSQL then enable read_only; (c) gateway binds 0.0.0.0:8000 — put TLS reverse proxy in front, bind `127.0.0.1:8000:8000` when proxied; (d) compose config validated with `docker compose config` only (no daemon here, images not built).

## 4. Workflows
- All have top-level `permissions: contents: read`; no `pull_request_target`; no `secrets.*` use, no secret echo; paths-filtered triggers.
- Applied: `persist-credentials: false` on every checkout, per-workflow `concurrency` with cancel-in-progress, `timeout-minutes` on jobs lacking one.
- Not applied (cannot resolve SHAs offline; will not guess): pin third-party actions to commit SHAs (`actions/checkout@v4`, `setup-python@v5`, `setup-java@v4`, `upload-artifact@v4`, `subosito/flutter-action@v2` — the last is third-party, highest priority). `flutter-action` uses `channel: stable` (floating) and `pip install` unpinned in e2e/mobile-live; use the constraints file above. Enable Dependabot for `github-actions` and `pip`.
- `apps/mobile/pubspec.yaml`: not modified; consider committing `pubspec.lock` for the app (currently gitignored) so CI builds are reproducible.
