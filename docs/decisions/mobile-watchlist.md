2026-10-14 | Watchlist/alerts UI uses only GET/POST /v1/watchlist, DELETE /v1/watchlist/{id}, GET /v1/alerts, POST /v1/alerts/{id}/read and /read-all via gateway; `evaluate` not used | evaluate is internal
2026-10-14 | Bell badge uses `unread_total` from GET /v1/alerts?unread_only=true&page_size=1; errors (e.g. guest 401) show no badge | no separate count endpoint
2026-10-14 | Mock repo `add` takes display hints (title, current price) because the mock has no sourcing; live ignores them | server resolves them from sourcing
