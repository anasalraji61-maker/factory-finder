# Security review round 2 (2026-10) - deferred items

Fixed in place (tests in `services/*/tests/test_security_review.py`): payments ledger double-post race (status CAS in `_move`),
webhook unicode-digit timestamp 500, demand daily-cap race (process lock + PG advisory lock), disclosure stripped by edited text,
supplier-controlled listing text injected into replies, non-http(s) signal/published URLs, trust report rate-limit state unbounded
(spoofed X-User-Id), notification prefs email validation (header injection), gateway admin-token guessing (throttle on failed 401s).

1. MEDIUM - notifications digest goes to a user-typed `email` with no ownership proof: any user can make the platform mail an
   arbitrary address (low volume: one digest/day/user). Needs email verification (token mail) or sending only to the gateway
   account email. Owner: notifications + gateway.
2. LOW - payments webhook `payment.confirmed` without `amount` still settles (contract marks amount optional). Signed by the
   provider secret, so trusted, but the real provider adapter should require it: make `amount` required for confirmed events in v2.
3. LOW - gateway proxy does not check `is_active` per request: a disabled user keeps API access until the access token expires.
4. LOW - rate limits and the trust report quota are per process (in memory); use Redis before running >1 replica.
5. LOW - trust `SnapshotStore` keys grow with every distinct supplier id queried (mock adapter answers any id).
6. INFO - payments/demand/notifications/trust/messaging trust `X-User-Id` on direct ports when no internal token is set (see
   security-review-2026-10.md item 4); payments webhooks are not reachable through the gateway (needs auth) - expose them on a
   dedicated ingress route that forwards only the raw body and `X-FF-Signature`.
7. INFO - tests/test_ws.py::test_pipe_and_identity is flaky under TestClient (CancelledError, retry_on_cancel helper); unrelated to code.
