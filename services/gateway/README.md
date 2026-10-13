# gateway (port 8000)

Auth (bcrypt + JWT: access 15 min, refresh 30 days), profile (`/v1/me`), `/v1/home` feed, and a reverse proxy mapping `/v1/*` path prefixes to services (see `ff_gateway/domain/routing.py`). Adds `X-User-Id`, `X-Internal-Token` (if `FF_INTERNAL_TOKEN`), `X-Request-Id`; upstream down -> 502, timeout -> 504. Contract: `contracts/openapi/gateway.yaml`.

Run: `uvicorn ff_gateway.main:app --port 8000`. Test: `../../.venv/bin/python -m pytest -q`.

Env (prefix `FF_GATEWAY_`): `JWT_SECRET` (unset -> ephemeral secret + warning), `DATABASE_URL` (sqlite+aiosqlite:///./gateway.db), `UPSTREAMS` (JSON overrides, e.g. `{"trust":"http://trust:8104"}`), `RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE`, `CORS_ORIGINS` (JSON list), `HOME_CLIENT` (http|mock), `ADMIN_TOKEN` (enables `/v1/admin/*`; unset -> 404), `UPSTREAM_TIMEOUT_SECONDS`; plus `FF_INTERNAL_TOKEN`.
Gaps: no WebSocket proxy, stateless refresh tokens, in-memory rate limiter.

## WebSocket proxy

`WS /v1/ws/conversations/{id}` is proxied to messaging (same path). Auth: `Authorization: Bearer <access>` or `?token=<access>`. Only the verified `X-User-Id` / `X-Supplier-Id` (and `X-Internal-Token` if configured) go upstream; client-supplied `user_id` and the token are never forwarded. Close codes: 4401 unauthenticated, 4403/4429 from messaging, 4404 unknown path, 1011 upstream unavailable. Note: access logs of the ASGI server may record `?token=`; prefer the header where possible.

## Supplier claims

`PATCH /v1/me {supplier_id}` records a **pending** claim (`supplier_claim_status`: none|pending|verified); pending/verified ids are unique (409). The gateway forwards `X-Supplier-Id` (HTTP and WS) to messaging only when status is `verified`. Admins (header `X-Admin-Token` == `FF_GATEWAY_ADMIN_TOKEN`, constant-time compare; 404 if unset, 401 if wrong) use `GET /v1/admin/supplier-claims?status=pending|verified`, `POST /v1/admin/supplier-claims/{user_id}/approve|reject`. Reject and `supplier_id: null` release the id and reset status to none. Startup adds the column on existing sqlite DBs; pre-existing claims become pending.
