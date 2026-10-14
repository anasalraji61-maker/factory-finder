2026-10-14 | Import-compliance advisor lives in logistics (`/v1/compliance/*`, `domain/compliance.py`, `data/compliance.json`) | reuses the incoterm/stage tables and duty-country conventions; no new service or network
2026-10-14 | Contract first: all compliance schemas in `contracts/openapi/logistics.yaml`; `common.schema.json` untouched | additive, keeps the shared schema stable
2026-10-14 | Incoterm payer per leg is derived from `BUYER_STAGES` (not duplicated) and a test ties it to quote lines | cannot drift from the landed-cost engine
2026-10-14 | Data is explicitly indicative: every response carries source, as_of 2026-10, confidence (low for IQ/GCC-ex-SA-AE/JO and any unknown destination) and the broker label; no live regulator lookup | compliance changes by decree; honesty over false precision
2026-10-14 | Product resolution: HS chapter -> 28 product groups, else category alias, else generic goods with lowered confidence + assumption | works with the partial info buyers have
2026-10-14 | EU is one profile for 27 members; unknown countries get a generic `ZZ` baseline (200, covered=false) instead of 404 | UI can always show the base documents
2026-10-14 | Quote `compliance_hint` is additive/optional and swallowed on error (uses the recommended option mode, quote incoterm, goods.hs_code/category) | cheap integration that can never break a quote
2026-10-14 | Gateway routing for `/v1/compliance` is requested, not implemented (outside lane): docs/requests/logistics-compliance-gateway.md | stay in lane
