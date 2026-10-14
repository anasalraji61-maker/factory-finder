# gateway (port 8000)

Auth (bcrypt + JWT: access 15 min, refresh 30 days), profile (`/v1/me`), `/v1/home` feed, and a reverse proxy mapping `/v1/*` path prefixes to services (see `ff_gateway/domain/routing.py`). Adds `X-User-Id`, `X-Internal-Token` (if `FF_INTERNAL_TOKEN`), `X-Request-Id`; upstream down -> 502, timeout -> 504. Contract: `contracts/openapi/gateway.yaml`.

Run: `uvicorn ff_gateway.main:app --port 8000`. Test: `../../.venv/bin/python -m pytest -q`.

Env (prefix `FF_GATEWAY_`): `JWT_SECRET` (unset -> ephemeral secret + warning), `DATABASE_URL` (sqlite+aiosqlite:///./gateway.db), `UPSTREAMS` (JSON overrides, e.g. `{"trust":"http://trust:8104"}`), `RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE`, `CORS_ORIGINS` (JSON list), `HOME_CLIENT` (http|mock), `ADMIN_TOKEN` (enables `/v1/admin/*`; unset -> 404), `UPSTREAM_TIMEOUT_SECONDS`; plus `FF_INTERNAL_TOKEN`.
Gaps: no WebSocket proxy, stateless refresh tokens, in-memory rate limiter.

## WebSocket proxy

`WS /v1/ws/conversations/{id}` is proxied to messaging (same path). Auth: `Authorization: Bearer <access>` or `?token=<access>`. Only the verified `X-User-Id` / `X-Supplier-Id` (and `X-Internal-Token` if configured) go upstream; client-supplied `user_id` and the token are never forwarded. Close codes: 4401 unauthenticated, 4403/4429 from messaging, 4404 unknown path, 1011 upstream unavailable. Note: access logs of the ASGI server may record `?token=`; prefer the header where possible.

## Supplier claims

`PATCH /v1/me {supplier_id}` records a **pending** claim (`supplier_claim_status`: none|pending|verified); pending/verified ids are unique (409). The gateway forwards `X-Supplier-Id` (HTTP and WS) to messaging only when status is `verified`. Admins (header `X-Admin-Token` == `FF_GATEWAY_ADMIN_TOKEN`, constant-time compare; 404 if unset, 401 if wrong) use `GET /v1/admin/supplier-claims?status=pending|verified`, `POST /v1/admin/supplier-claims/{user_id}/approve|reject`. Reject and `supplier_id: null` release the id and reset status to none. Startup adds the column on existing sqlite DBs; pre-existing claims become pending.

## Admin demand proxy and console

With the admin token set (404 unset / 401 wrong): `GET /v1/admin/overview` (`pending_supplier_claims`, `pending_drafts` (null if demand is down), `users`) and an allow-listed proxy `/v1/admin/demand/{signals, signals/poll, signals/{id}, drafts, drafts/{id}, drafts/{id}/approve|reject|mark-published|outcome, quota}` -> demand `/v1/...`. Upstream always gets `X-User-Id: admin` and `X-Internal-Token`; client identity headers (incl. X-Admin-Token, Authorization) are never forwarded. Upstream `demand` defaults to `http://localhost:8110` (add it to `FF_GATEWAY_UPSTREAMS` in docker-compose).
`FF_GATEWAY_SERVE_ADMIN=true` serves `apps/admin` at `/admin/` (default off; `FF_GATEWAY_ADMIN_DIR` overrides the folder). CORS stays closed: a separately hosted admin page must be listed in `FF_GATEWAY_CORS_ORIGINS`.

## Security notes
- Refresh tokens are single-use and tracked in `refresh_tokens` (hashed jti + family). Reusing a rotated token revokes the family; `POST /v1/auth/logout` revokes it explicitly.
- CORS: no origins allowed unless `FF_GATEWAY_CORS_ORIGINS` (JSON list) is set.
- WebSocket auth accepts `?token=<access jwt>` (clients cannot set headers); uvicorn access logs are redacted, any proxy in front must scrub it too.
- Verified `X-Supplier-Id` (admin-verified claims only) is forwarded to messaging and rfq; client-sent values are never forwarded.
