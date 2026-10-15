# gateway: passthrough for feed mutes

The feed service now has a per-viewer mute list (contract: `contracts/openapi/feed.yaml`). The gateway needs to route these user routes to the feed service like the other `/v1/feed/*` routes (authenticated; forward `X-User-Id` and, when verified, `X-Supplier-Id`):

- `GET /v1/feed/mutes`
- `PUT /v1/feed/mutes/{supplier_id}`
- `DELETE /v1/feed/mutes/{supplier_id}`

If the gateway uses an explicit allow-list or per-route method table, add these (PUT and DELETE included). No new env vars. Until then the routes work only when calling the feed service directly.

Status: DONE (covered by the `/v1/feed` prefix; all methods proxied, bearer required; tests in services/gateway/tests/test_passthrough_detect_mutes.py).
