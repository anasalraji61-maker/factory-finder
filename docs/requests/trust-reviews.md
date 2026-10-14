# Request: trust <- rfq review aggregates

From: rfq (deal-reviews). To: trust owner. Status: open (no trust code was changed).

rfq exposes, public and unauthenticated, `GET /v1/suppliers/{supplier_ref}/review-summary`
(`contracts/openapi/rfq.yaml#ReviewSummary`):

```json
{"supplier_ref": "sup_a", "count": 7, "average": "3.71",
 "histogram": {"1": 1, "2": 0, "3": 1, "4": 3, "5": 2},
 "sub_ratings": {"quality": "4.67", "communication": null, "shipping": null},
 "completed_deals": 5}
```

Trust already has `rating_avg` (0..5, float) and `reviews_count` signals with Bayesian shrinkage
(`review_prior_mean`, `review_prior_weight`). Proposed wiring, behind a new `ReviewsClient` (http + deterministic mock,
same pattern as the other trust clients, switchable off by config, short cache):

- `rating_avg = float(average)`, `reviews_count = count` (only when `count > 0`; trust's shrinkage handles small samples).
- Optionally a new additive signal `completed_deals` from the same payload.
- Gateway/`supplier_ref` is the same id trust scores (`/v1/trust/suppliers/{id}`).
- Reviews are verified-purchase only (buyer of a paid deal), so they can be weighted above scraped marketplace ratings.
