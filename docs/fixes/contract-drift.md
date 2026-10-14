# Contract drift found by scripts/contract_validate.py (2026-10-14)

112 responses over 89 operations validated; 20 findings (de-duplicated per path/location), all allowlisted in
`scripts/contract_validate.allow.json`. Route sets match (`contract_check.py` all OK). None is a service crash or a data
bug; all are contract-side (services/contracts were not edited by this task). Owners: architect (contracts), then the
named service only if the contract is deliberately kept stricter.

## A. Contract too strict: nullable optional fields (fix: `type: [string, "null"]`, additive)
| Spec / operation | Field(s) |
|---|---|
| sourcing GET /v1/search | `sources[].warning` is null when no fallback happened |
| rfq POST/GET /v1/requests, /v1/requests/{id} | `deadline`, `description` |
| rfq POST/GET /v1/requests/{id}/offers | `notes`, `supplier_ref`, `valid_until` |

## B. Contract schema bug: `allOf` + `additionalProperties: false` (rfq)
`Request = allOf[RequestCreate, {id, owner_id, status, ...}]` and `Offer = allOf[OfferCreate, {...}]` where the first
branch has `additionalProperties: false`, so no real response can ever validate (the response-only fields are rejected).
Affects POST/GET /v1/requests, GET /v1/requests/{id}, POST/GET /v1/requests/{id}/offers (and anything else referencing
them, e.g. deals if they embed them). Fix: remove `additionalProperties:false` from the shared base (keep it only on the
create request body via a separate schema) or use `unevaluatedProperties: false` on the composed schema. Mobile codegen
from these schemas is affected if it honours additionalProperties.

## C. Contract mismatch, gateway
- POST /v1/auth/refresh: response `user` is null (only tokens are refreshed); contract says object. Make it
  `[object, "null"]` or drop it from `required`/properties.
- PATCH /v1/me: `default_destination.point` is returned as null for city-only destinations while `Location.point`
  (common.schema.json, architect-owned) does not allow null. Make `point` nullable (additive).

## D. Service bugs
None found.

## Coverage notes
Not validated (no response schema in the contract): `/health` of gateway, trust, messaging, notifications, demand,
payments and `DELETE /v1/watchlist/{id}` (204). Gateway `/v1/admin/demand/*` is a passthrough with no schema in
gateway.yaml, so it is validated against the demand contract. Error bodies (422/404/401) are validated against the
documented `Error` schema where the call was made.
