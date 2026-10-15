# gateway: uvicorn launch flags (from security review h)

Owner of infra/Docker: please start the gateway with `--no-server-header` (hides `Server: uvicorn`), without `--proxy-headers`/`--forwarded-allow-ips` (the gateway resolves X-Forwarded-For itself via `FF_GATEWAY_TRUSTED_PROXIES`) and with `--timeout-keep-alive 5`. Document `FF_GATEWAY_JSON_MAX_BODY_BYTES` (1 MiB) in the reverse proxy: its `client_max_body_size` should be at least `FF_GATEWAY_MAX_BODY_BYTES` for `/v1/media` only.
