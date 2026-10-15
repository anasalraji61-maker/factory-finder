# notifications -> sourcing: signals needed for reliable alerts

From: notifications QA. Additive only.

1. `GET /v1/listings/{id}` answers 404 both for "delisted / hidden / pending_review" and when every adapter timed out (`_first` swallows errors). Notifications reads 404 as delisted and later raises a `back_in_stock` alert when the listing returns, so a transient adapter outage yields a false alert. Please answer `503 upstream_timeout` when adapters failed/timed out and keep 404 for a definite absence (notifications already treats 5xx as "sourcing unavailable": no state change, no alert).
2. `GET /v1/search`: notifications treats a page as degraded (no alerts, no state change) when top-level `warning` is set, any `sources[].status != ok`, or any `sources[].warning` is set (mock substituted). Please add an optional top-level `warning` (e.g. `partial_results: ...`) to the search 200 body in `contracts/openapi/sourcing.yaml`, as already done for `/similar` and `/recommendations`.
3. Price comparison is same-currency only (no FX in v1): a listing that changes currency re-bases the baseline silently, and a target in another currency never fires. Only a percentage threshold exists (no absolute threshold). If absolute thresholds or FX are wanted, logistics' FX contract would be the source; not requested yet.
