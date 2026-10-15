# Duty / VAT table verification (services/logistics/src/ff_logistics/data/duties.json)

Reviewed 2026-10-15. Status: NOT a blocker; table stays "indicative, verify with broker".

## Internal consistency (automated audit)
- All rates are percent numbers (0..150), never fractions; VAT 0..27; ranges bracket the default rate.
- Every country in `lanes.json` regions has a duty entry except IL, which falls back to a labelled placeholder (10% duty, 0% VAT, range 0-30 / 0-25, confidence low, as_of 2026-10). The fallback now carries range, as_of and confidence (was missing).
- All 2-digit HS chapter keys valid. Coverage is only chapters 39,52,61,62,72,73,84,85,87,94; all others use the country default (labelled "default duty" in the rule text). Known gap: food, chemicals, pharma, vehicles' parts etc.
- Fixed: HK and SG were labelled confidence "high" while unverified; now "medium". Rule: no row is "high".
- Iraq: added range 0-30% and a note (see below). De minimis values are all low/medium and flagged with status (US suspended, EU being phased out); not verified.

## Cross-checks (web)
| Item | Result | Source |
|---|---|---|
| TR VAT 20% standard | Verified (since 10 Jul 2023) | https://trykintsugi.com/sales-tax-guides/middle-east/turkey.md |
| AE VAT 5% on customs value + duty; most goods 5% duty (GCC CCT) | Verified | https://www.commenda.io/uae/import-vat |
| IQ tariff | Partly: Jan 2026 tariff increase, brackets 5-30%, 99 chapters; 25% cut of ASYCUDA reference values (1 Feb 2026). Our flat 5% for most chapters is not confirmed and is probably low for some lines. Not changed (no clear contradiction); range widened, note added, confidence stays low | https://www.shafaq.com/en/Economy/Iraq-lowers-customs-import-value-estimates-by-25 |
| US additional duty on CN (+15) | NOT verified: sources found were paywalled or rate-free; US-China tariffs changed repeatedly in 2025-26 (avg ~34% bilateral per Feb 2026 CRS summary). Left as is, confidence low | https://globalsanctions.com/2026/03/us-congressional-research-briefing-on-us-china-tariffs |
| CN VAT 13%, EU member VAT rates, other countries | Not checked online (from memory) |  |

Follow-up: Iraq per-chapter rates need the official 2026 schedule or a broker.
