# sourcing -> contracts: additive `warning` on recommendations / similar

Request (architect): add optional `warning: string` to the 200 bodies of `GET /v1/recommendations` and `GET /v1/listings/{id}/similar` in `contracts/openapi/sourcing.yaml` (set to `partial_results: ...` when the time budget cut work short; omitted otherwise), and `503 upstream_timeout` for `/similar`. Service already emits it; additive only.
