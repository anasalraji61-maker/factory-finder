2026-10-13 | Money stored as decimal strings in SQLite, Decimal in code; commission rounded half-up to cents | exactness, no SAWarning on SQLite
2026-10-13 | Min fee 25 USD converted to the deal currency with a static rate table (10 currencies, others -> 422 unsupported_currency) | no FX dependency in rfq; logistics owns live FX
2026-10-13 | Request expiry/offer validity applied lazily on every call (sweep) | no worker needed
2026-10-13 | Added additive endpoints close/reject/withdraw and GET suggestions; GET /v1/requests has scope=mine|public | needed to complete the state machine and the public feed
2026-10-13 | Offers visible to the buyer (all) and to their own supplier only; deals visible to the two parties, others get 404 | privacy
2026-10-13 | Accepting an offer rejects all other active offers and awards the request atomically | single transaction
