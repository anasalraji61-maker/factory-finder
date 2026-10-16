# Fuzz findings (scripts/fuzz_contracts.py)

**Status 2026-10-16: addressed, pending re-run.** The gateway `/v1/home` now applies a per-section timeout and returns `degraded` with warnings instead of stalling, and non-envelope 4xx responses from upstreams are normalised to the `{error:{code,message}}` envelope. Re-run `make fuzz` to confirm 0 findings; the run below is the historic one.

_Run 2026-10-16: 150 operations, 25257 requests, 1 distinct findings._

Checks: no 5xx, `{error:{code,message}}` envelope on every 4xx, no stack traces / filesystem paths / driver names in bodies, latency < 5s. Re-run: `make fuzz`.

## 1. slow: GET /v1/home (1 hits)

- Case: `query:q`; 5.6s
- Request: `"GET /v1/home q={'q': 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA ct=None body='None'"`
- Response excerpt: `'{"user":{"id":"usr_39dc90ac39994be48c22dc1d3c91c92b","name":"Fuzz User","language":"ar"},"warnings":[],"categories":[{"slug":"product","name":"Products","name_ar":"منتجات","children":[{"slug":"furniture","name":"Furniture","name_ar":"أثاث","children":[]},{"slug":"lighting","name":"Lighting","name_ar'`


## Fixed during the first run (all re-verified clean)

- 30 GET routes returned 500 for a NUL/control character in a path segment (httpx.InvalidURL in the gateway proxy):
  `_suspicious_path` in `services/gateway/src/ff_gateway/api/proxy.py` now refuses control characters (404 envelope);
  same guard in `_seg` of `api/admin_demand.py`.
- `GET /v1/admin/supplier-claims?page=99999999999999999999999` and `GET /v1/watchlist?offset=<huge>` returned 500
  (SQLite OverflowError): capped `page`/`offset` at 1,000,000 in `api/admin.py` and notifications `api/routes.py`.
- Observation only: the `slow` entry above is a one-off 5.1-5.6 s on `/v1/home` with a 30 KB `q` (the param is ignored;
  the page aggregates several upstreams), not reproducible per request; treat as a cold-aggregation latency note.
