# Request (logistics -> gateway owner): route `/v1/compliance/*` to logistics

Logistics (port 8102) now serves, per `contracts/openapi/logistics.yaml`:
- `POST /v1/compliance/checklist`
- `GET /v1/compliance/countries`, `GET /v1/compliance/countries/{code}`
- `GET /v1/compliance/incoterms`

Needed in `services/gateway/src/ff_gateway/domain/routing.py`:
- add `"/v1/compliance": "logistics"` to the prefix map (next to `/v1/hs`);
- make GET `/v1/compliance` public like `/v1/hs` (static indicative data, lets the app show it pre-login); the POST checklist can stay authenticated or be made public too (no user data, deterministic) - gateway owner's call;
- document the proxy surface in `contracts/openapi/gateway.yaml` if the gateway lists proxied prefixes.

No new env vars. `POST /v1/quotes/landed-cost` already returns the optional `compliance_hint` through the existing `/v1/quotes` route.
