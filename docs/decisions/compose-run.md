2026-10-14 | Could not run compose for real (Docker Hub 403 in sandbox); validated statically and documented in docs/DEPLOY.md | no pull of python:3.12-slim possible
2026-10-14 | Added FF_E2E_BASE_URL to scripts/e2e.py (remote mode skips spawn + direct-port steps) | lets e2e run against compose where only the gateway is published
2026-10-14 | Gateway depends_on all services healthy; start_period 20s on healthchecks; added FF_GATEWAY_ADMIN_TOKEN passthrough, .dockerignore, make compose-e2e | startup ordering and fewer false-unhealthy states
