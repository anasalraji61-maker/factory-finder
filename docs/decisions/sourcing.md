2026-10-13 | Mock catalog is 60 listings (owner quota), not 120 | AGENTS.md says >=120; data file is generated from compact rows so it can grow without code changes.
2026-10-13 | Engine does keyword relevance/filters for every adapter; adapters only pre-filter (kind, country) | One consistent ranking regardless of source; real APIs get `keywords_en` for their own query.
2026-10-13 | Query terms are AND-ed, each matched through bilingual synonym groups | Predictable results; Arabic query finds English-titled items.
2026-10-13 | Price filters compare only USD-priced listings; other currencies pass through | No FX in sourcing; logistics owns FX. Revisit via a request to logistics.
2026-10-13 | `condition` filter also accepts `refurbished` (additive to new|used|any) | Common.schema Condition has refurbished.
2026-10-13 | Real-adapter request signing/endpoints are skeletons to be verified against provider docs before enabling | No network/keys in the sandbox.
2026-10-13 | Trust default mode is `mock` in dev; set FF_SOURCING_TRUST_MODE=http + TRUST_BASE_URL in compose | Search must work without the trust service.
2026-10-13 | Listing ids for real sources are `lst_<source>_<native id>`; supplier `sup_<source>_<id>` | Avoid collisions with mock `lst_nnnn`/`sup_cc_nnn`.
