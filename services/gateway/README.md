# gateway (port 8000)

Auth (bcrypt + JWT: access 15 min, refresh 30 days), profile (`/v1/me`), `/v1/home` feed, and a reverse proxy mapping `/v1/*` path prefixes to services (see `ff_gateway/domain/routing.py`). Adds `X-User-Id`, `X-Internal-Token` (if `FF_INTERNAL_TOKEN`), `X-Request-Id`; upstream down -> 502, timeout -> 504. Contract: `contracts/openapi/gateway.yaml`.

Run: `uvicorn ff_gateway.main:app --port 8000`. Test: `../../.venv/bin/python -m pytest -q`.

Env (prefix `FF_GATEWAY_`): `JWT_SECRET` (unset -> ephemeral secret + warning), `DATABASE_URL` (sqlite+aiosqlite:///./gateway.db), `UPSTREAMS` (JSON overrides, e.g. `{"trust":"http://trust:8104"}`), `RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE`, `CORS_ORIGINS` (JSON list), `HOME_CLIENT` (http|mock), `UPSTREAM_TIMEOUT_SECONDS`; plus `FF_INTERNAL_TOKEN`.
Gaps: no WebSocket proxy, stateless refresh tokens, in-memory rate limiter.

## WebSocket proxy

`WS /v1/ws/conversations/{id}` is proxied to messaging (same path). Auth: `Authorization: Bearer <access>` or `?token=<access>`. Only the verified `X-User-Id` / `X-Supplier-Id` (and `X-Internal-Token` if configured) go upstream; client-supplied `user_id` and the token are never forwarded. Close codes: 4401 unauthenticated, 4403/4429 from messaging, 4404 unknown path, 1011 upstream unavailable. Note: access logs of the ASGI server may record `?token=`; prefer the header where possible.
