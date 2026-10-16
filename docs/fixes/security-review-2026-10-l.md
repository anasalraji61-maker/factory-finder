# security review 2026-10 l (cross-service trust, SSRF, injection, numerics)

Scope: attacker-eyes pass over all services; did not repeat items from reviews b-k.

## Fixed
1. **High (availability, unauthenticated): unbounded Decimals on the public logistics endpoints.** `POST /v1/quotes/landed-cost`
   (public through the gateway) accepted `total_weight_kg`, `quantity`, `total_value.amount` etc. such as `1e999999`; the engine
   spun for minutes (request hung >2 min in the test). Amounts, quantities, weights and volumes are now bounded
   (`max_digits`, `decimal_places`, upper limits) in `services/logistics/src/ff_logistics/schemas.py`, also `/v1/fx/convert`.
   Tests: `services/logistics/tests/test_security_review_l.py`.
2. **Low: notifications money pattern allowed unlimited digits** (`^-?[0-9]+(\.[0-9]+)?$`, watch targets / saved-search prices).
   Now at most 18 integer and 8 fractional digits (`domain/money.py`). Tests: `services/notifications/tests/test_security_review_l.py`.

## Verified clean
- Internal-token middleware in every service (constant-time compare, exempt only `/health`, `/ready`, payments webhooks which use HMAC);
  logistics/demand/messaging/notifications enforce per-route dependencies. `/v1/internal/*` has no gateway route (404).
- No raw SQL built from user input (only constant `text()`; advisory-lock key bound as parameter). No pickle/yaml.load/marshal.
- No user-controlled URL is fetched server-side: HTTP adapters use configured bases, redirects off, path parts `quote()`d (tracking);
  freight/messaging attachment URLs are stored, never fetched (messaging restricts to media host + prefix).
- JWT: `typ` checked per use (access vs refresh vs ws), HS-only, iss/aud, token version. Admin is a separate header token, no JWT role claim.
- Gateway/`MePatch`/`RegisterIn` use `extra="forbid"`; supplier identity only from DB-verified claim.

## Open (low, not fixed)
1. Sourcing guards identity headers by path allow-list (`/v1/my`, `/v1/admin`, `/v1/internal`, suffix `/report`, `/events`) rather than
   deny-by-default; a new route reading `X-User-Id` outside those paths would be unguarded if the service were reached directly.
   Also a trailing-slash `/report/` skips the suffix test (FastAPI redirects, then the check applies). Reachable only from the internal network.
2. Freight attachment URLs accept odd IP spellings with dots (e.g. `0x7f.1`) as hostnames; stored and shown only, never fetched.
3. Pre-existing ruff I001 in `services/payments/src/ff_payments/db.py` (not touched here).
