# Operations notes

## Probes
- Liveness: `GET /health` on every service. Readiness: `GET /ready` (200 ready / 503 unavailable; checks DB where one exists). Neither needs the internal token.
- Gateway `/ready` also returns `upstreams: {name: bool}`; status `degraded` (HTTP 200) if a backend is down, 503 only when the gateway DB is down.

## Logs
- One JSON line per request on stdout: `ts, level, service, request_id, method, path, status, duration_ms, user_id`. `FF_LOG_FORMAT=text` for local dev.
- Correlate by `request_id`: the gateway accepts/generates `X-Request-Id` and forwards it to every upstream, which echo it in responses and logs.
- Never logged: query strings, Authorization, tokens, bodies. (WebSocket `?token=` is also redacted in uvicorn access logs; scrub it in any extra proxy.)

## Gateway behind a proxy / LB
- Set `FF_GATEWAY_TRUSTED_PROXIES` to the proxy CIDRs (e.g. `10.0.0.0/8,172.16.0.0/12`); otherwise all clients share the proxy's IP for rate limiting. Do not include untrusted networks: anyone in the list can spoof `X-Forwarded-For`.
- Limits (env, prefix `FF_GATEWAY_`): `RATE_LIMIT_PER_MINUTE` (300), `AUTH_RATE_LIMIT_PER_MINUTE` (30), `USER_WRITE_RATE_LIMIT_PER_MINUTE` (120, 0 off), `RATE_LIMIT_MAX_KEYS` (50000).
- The limiter is in-memory per process; with N replicas the effective limit is N x. Move to Redis before scaling out.
