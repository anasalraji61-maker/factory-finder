# Decision: price history + similar/recommendations (sourcing)

2026-10-15 - Added price observations (`price_observations`, migration 0003), `GET /v1/listings/{id}/price-history`, `GET /v1/listings/{id}/similar`, `GET /v1/recommendations`; contract additive in `contracts/openapi/sourcing.yaml`.

- Observed value = headline (min) unit price; one currency per series (newest currency wins). Recorded on search page items, detail fetches and native publish/update; dedupe = latest observation within 6 h with same price+currency; cap 500 points/listing and 400 days. Recording is best effort and never fails a request.
- Mock-catalog listings are never stored: history is a deterministic seeded daily series (sha256 of id+day) ending exactly at the current price, flagged `synthetic: true`, so the app can chart without waiting for data.
- Trend: first vs latest observation in the window; |change| <= 1% = flat; < 2 observations or buckets = `insufficient_data` (no change_pct, no hints). `hints.suggested_target` (period low) is the additive hook for alert evaluation; notifications is not modified.
- Similarity is rule-based and explainable (weights in README), bounded to 300 candidates and 60 trust lookups; red-band suppliers are demoted, not hidden; the same supplier is demoted, not excluded.
- Recommendations carry no user state: the client passes recent ids (max 20, most recent first), nothing is stored or tied to PII. `country` is read as a preferred ORIGIN country (small boost). Gateway: `/v1/recommendations` added to the routing table and public GET prefixes (gateway.yaml additive; test in gateway/tests/test_proxy.py).
- Note: `contract_check` reports sourcing drift only for `/v1/internal/users/{}/...` entries that another change added to the contract (not part of this work); new routes match.
