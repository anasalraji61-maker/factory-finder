# ff-common

Shared Python utilities, no business logic. Today: `ff_common.ratelimit` (window rate limiter).

- `WindowLimiter(limit, window_seconds, mode=sliding|fixed|calendar, redis=None, on_error=memory|open|closed, on_full=evict|closed)`.
  `await limiter.hit(key)` -> `Decision(allowed, limit, remaining, retry_after)`. In-memory by default; pass a
  `redis.asyncio` client (`make_redis_client(url)`) to share counters across replicas (INCR + EXPIRE; `sliding`
  degrades to a fixed window on Redis). If Redis raises: `memory` (default, warn once), `open` or `closed`.
- Services (messaging, assistant) cannot import this package at build time (their image/CI only contain
  `services/<name>`), so each carries a byte-identical copy as `ratelimit.py`; `tests/test_ratelimit.py` fails on drift.
  After editing the canonical file: `cp packages/py-common/src/ff_common/ratelimit.py services/<svc>/src/ff_<svc>/ratelimit.py`.
- Env (read by the services, not this package): `FF_REDIS_URL` (empty = in-memory). Optional extra `redis` (`redis>=5`).

Run: `cd packages/py-common && python -m pytest`. Tests use a fake Redis; no network.
