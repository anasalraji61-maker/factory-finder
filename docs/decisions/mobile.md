2026-10-13 | Single agent built core + discover + logistics + profile | The earlier multi-agent split was interrupted; one agent keeps the contract consistent. Module boundaries (features/ folders, FeatureModule, path-only navigation) are still respected.
2026-10-13 | i18n tables are `key: (ar, en)` records via `bilingual()` | Guarantees every key exists in both languages by construction.
2026-10-13 | Logistics has its own listing prefill fixture (`mockPrefills`) | Contract forbids importing discover internals; live mode uses GET /v1/listings/{id}.
2026-10-13 | Last quote kept in `lastQuoteProvider`; results route reads it | Avoids passing complex `extra` objects through go_router.
2026-10-13 | Avoided Card/Dialog/TabBar ThemeData sub-themes and Dropdown widgets | Their types/params changed across Flutter 3.22-3.35; chips and bottom sheets are stable.
2026-10-13 | Mock FX/freight tables are fixed constants, estimates carry -8%/+12% range | Deterministic tests; labeled as estimates per CLAUDE.md rule 8.
