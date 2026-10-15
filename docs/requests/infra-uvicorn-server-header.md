# Request: infra - uvicorn `Server` header

Outside the logistics/trust/contracts lane (process launch flags belong to infra/Docker). Please start every service with `--no-server-header` (hides `Server: uvicorn`), plus `--timeout-keep-alive 5`; see also `docs/requests/gateway-uvicorn-flags.md` (gateway: no `--proxy-headers`). Applies to logistics and trust too.
