# Request: gateway passthrough for tracking reference detection

From: tracking. To: gateway. Status: open (tracking side done).

tracking now serves `GET /v1/references/detect?q=` (additive, `contracts/openapi/tracking.yaml`). The gateway route table
(`services/gateway/src/ff_gateway/domain/routing.py`) maps `/v1/shipments` and `/v1/validate` to `tracking` but has no entry
for `/v1/references`, so the endpoint is unreachable through the gateway. Needed: add `"/v1/references": "tracking"`
(public, same auth treatment as `/v1/validate`; the endpoint needs no `X-User-Id`). Mobile can use it to auto-select the
reference type in the add-shipment form.
