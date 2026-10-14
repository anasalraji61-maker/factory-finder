# Security review 2026-10-c (open items)

1. **rfq / payments / notifications internal token fails open when unset** (`FF_INTERNAL_TOKEN` empty): `POST /v1/internal/deals/{id}/payment-status`
   then accepts anyone who can reach the rfq port (amounts are guessable from the deal). The gateway never routes it, so exposure is
   network-level only. Production deploys MUST set FF_INTERNAL_TOKEN; a fail-closed `FF_ENV=production` check in each service's
   `create_app` is recommended (cross-cutting, not done here: it changes every service's startup contract).
2. **Resend-verification throttle is per address**: anyone can burn a victim's 1/min resend budget (minor DoS; no enumeration). Accepted.
3. **Rate-limit in-memory store fails open on eviction** (>50k live keys); needs ~50k distinct IPs/users per window, so low risk. Use Redis in prod.
4. **Gateway does not re-check `is_active` on ungated proxied routes**: a disabled user keeps access until the 15 min access token expires.
