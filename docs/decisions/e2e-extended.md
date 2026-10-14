2026-10-14 | e2e_extended.py reuses e2e.py helpers and boots its own stack with extra env (sourcing admin token, report threshold 2, tracking relay on, assistant quota 3) | keeps e2e.py untouched and fast
2026-10-14 | Email verification runs against an in-process gateway (ASGITransport + MockMailer) | the mock outbox lives in gateway memory and is not observable over HTTP
2026-10-14 | Tracking relay is driven by inserting a tracking_outbox row into the local SQLite file | the mock provider yields no status change on demand
2026-10-14 | Compliance flow probes known paths and SKIPs when absent | no compliance endpoints exist yet
2026-10-14 | smoke_prod.py accepts 401 or 404 for admin routes and only WARNs on missing X-RateLimit headers | 404 when no admin token is configured, 401 when set; headers exist only on 429
