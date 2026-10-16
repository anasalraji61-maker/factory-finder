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

## Official-source verification pass (2026-10-16)
Only items whose official page was actually read are marked verified (new `vat_verification` object per country, `de_minimis.verification` for US). Duty rates stay unverified for every country; entry-level confidence/label unchanged.

| Item | Result | Official source read |
|---|---|---|
| SA VAT 15% | Verified (ZATCA worked import example: SAR 600,000 CIF -> SAR 90,000 VAT). No general de minimis found (only traveller SAR 3,000 and GCC SAR 10,000 figures); table's SAR 1,000 stays unverified | https://zatca.gov.sa/en/HelpCenter/guidelines/Documents/Guideline-on-Imports-and-Exports-under-VAT-Provision.pdf |
| GB VAT 20% | Verified. GBP 135 threshold not confirmed (page fetched lacked it) | https://www.gov.uk/vat-rates |
| EG VAT 14% | Verified (Law 67/2016 Art. 3, from FY 2017/18) | https://www.eta.gov.eg/sites/default/files/2024-02/Law-english-no.67-2016.pdf.pdf |
| DE VAT 19% | Verified for standard rate (reduced 7%); import VAT assumed to mirror domestic rates (page does not say so explicitly). EU EUR 150 duty waiver phase-out not confirmed | https://www.zoll.de/DE/Fachthemen/Arbeit/Steuern/Umsatzsteuer/umsatzsteuer_node.html |
| AE VAT 5% | Verified (weak: FTA page only labels calculator "VAT 5%") | https://tax.gov.ae/en/taxes/vat.aspx |
| US de minimis | Status suspended + statutory repeal effective 2027-07-01 verified; USD 800 historical threshold per CBP FAQ | https://www.whitehouse.gov/fact-sheets/2026/06/fact-sheet-president-donald-j-trump-strengthens-customs-enforcement/ |
| TR VAT 20% | Still only non-official source; gib.gov.tr blocked by robots | - |
| JO VAT 16% | NOT verified (istd.gov.jo and customs.gov.jo pages read did not state the rate) | - |
| KW (5% duty, 0% VAT) | NOT verified (no official page found stating it) | - |
| IQ tariff / 0% VAT | NOT verified (customs.mof.gov.iq blocked by robots.txt) | - |
| FR, IT, etc. EU VAT; CN VAT | Not checked |  |
