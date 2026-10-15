# e2e-extended findings

No blocking bugs found: all extended flows pass. Minor observations (no service edited):

1. Gateway does not forward `X-Quota-Remaining` from the assistant (`FORWARD_RESPONSE_HEADERS` in
   `services/gateway/src/ff_gateway/api/proxy.py` lacks it), so clients cannot show remaining quota. The 429 +
   `Retry-After` do arrive. Additive fix: add `x-quota-remaining` to the set.
2. The gateway sends `X-RateLimit-*` only on 429 responses, not on normal ones (smoke_prod.py reports a WARN).
3. No compliance endpoints (data export / account deletion / consent) exist; the extended step SKIPs.

Status 2026-10-15: item 3 is partly resolved: `GET /v1/me/export` and account deletion endpoints now exist in `services/gateway/src/ff_gateway/api/account.py` (see docs/DB.md, Gateway account tables). Items 1 and 2 not re-verified in this pass.
