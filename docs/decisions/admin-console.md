2026-10-14 | Admin proxy forwards fixed actor id `admin` (not per-person) to demand | one shared X-Admin-Token means no individual identity; audit log shows `admin`. Per-admin accounts are a later change.
2026-10-14 | Proxy is an explicit allow-list (not a wildcard) and admin page is static, token in sessionStorage | minimises what a leaked token can reach; no build step or CDN keeps supply chain empty.
2026-10-14 | `FF_GATEWAY_SERVE_ADMIN` default off; CORS default stays closed | admin UI is opt-in; same-origin mount avoids CORS entirely.
2026-10-14 | docker-compose gateway `FF_GATEWAY_UPSTREAMS` lacks `demand` (outside gateway lane) | default `http://localhost:8110` works locally; orchestrator should add `"demand": "http://demand:8110"` and mount/copy apps/admin for serving.
