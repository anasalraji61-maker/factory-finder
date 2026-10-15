# Logistics accuracy review (2026-10)

Scope: `services/logistics`, `services/geo`. 16 lanes run through the engine with mock FX and both mock geo and the
real geo dataset (in-process ASGI): Shenzhen->Basra 20'/40', Guangzhou->Erbil air 500 kg, Istanbul->Baghdad road,
Shanghai->Hamburg, Ningbo->Los Angeles, Yiwu->Dubai LCL, Guangzhou->Riyadh, Shanghai->Cairo, Mumbai->Baghdad 20',
Shanghai->Baghdad rail, Izmir->Berlin road, Shenzhen->Baghdad air DDP, Rotterdam->Lagos FOB, Shanghai->Basra CIF (IQD),
Shenzhen->Istanbul without insurance (EUR). Regression tests: `services/logistics/tests/test_accuracy_review.py`.

## Fixed
1. **Nearly full truck was discounted.** Road/inland haul scaled the price linearly with fill, so a 20 t / 50 m3 load
   (83% full) was charged 83% and labelled "LTL". Now `cargo.truck_billing_factor`: >=70% fill = full truck, below
   scales to the 70% mark, floor 30%, multi-truck = full. Istanbul->Baghdad 20 t went USD 2,652 -> ~3,200.
2. **Cost lines had no timestamp.** The contract `CostLine` has no date field, so `source` now ends with
   `; priced <UTC ts>; FX <provider> <rates ts>` on every line (goods included). Request for a first-class field below.
3. **Silent fallbacks.** Destination without a duty table (generic 10% duty, 0% VAT) and countries missing from the
   region table (Europe handling/lanes assumed) now add an explicit low-confidence assumption to the quote.
4. **Russia VAT** 20% -> 22% (in force since 2026-01-01).

## Checked and OK (rough benchmarks, mid-2026 market)
- Sea FCL China->Iraq: 20' USD 1,670, 40' USD 2,700 (market ~1,500-3,000 / 2,500-4,500, volatile). China->Hamburg 40'
  USD 3,300; China->US West Coast 40' USD 4,300; India->Gulf 20' USD 620 (low end).
- Air China->Iraq 500 kg: ~USD 4.07/kg all-in (market 3.5-6). Volumetric 167 kg/m3 and LCL 1 t = 1 m3 correct.
- Insurance 0.2-0.35% of 110% of value, minimum USD 25: in range.
- VAT base = customs value + duty (SA 15%, EG 14%, TR 20%, DE 19%, AE 5%, IQ none): correct. Customs value follows
  incoterm (EXW adds origin legs, FOB freight+insurance, CFR insurance, CIF/DAP/DDP none).
- Incoterm stages: CIF drops main leg+insurance, DDP leaves goods only (min = max), FOB drops origin lines.
- Money: USD internally, one conversion, `ROUND_HALF_UP`, IQD/JPY/KRW/VND/IRR whole units; displayed totals are the sum
  of already-rounded lines and min/max straddle it. Every non-goods line is `estimate: true`; totals carry a range.
- Real geo (hubs, distances) works through the HTTP client (Dammam/Basra/Ain Sokhna/Long Beach chosen sensibly).

## Data-confidence caveats (not code bugs; need licensed data)
- All rates are a static table ("approx. rate table v1", as of 2026-10), not live. Freight swings +-50% in a year
  (Red Sea / Hormuz, Section 301 pull-forwards); the +-15% range on the main leg understates that. Live provider is OFF
  and UNVERIFIED.
- 41 older `duties.json` entries have no `confidence`/`as_of`/ranges (IQ, TR, SA, AE, EG, US, DE... the biggest
  corridors). Only the 29 round-3 countries are labelled. Duties use 2-digit HS chapter rates, not 6/8-digit lines.
- US: flat +15% "additional" on CN origin is a placeholder; Section 301 (7.5-100%), IEEPA/reciprocal tariffs and
  MPF/HMF fees are not modelled. Mexico CN +15% likewise (real rates up to 35-50%). Totals for CN->US can be off by
  tens of percent.
- Iraq: extra levies (reconstruction/stamp, COSQC inspection fees) and port-specific charges not modelled; Iraq
  inland haul for a container (e.g. Basra port->Basra city USD 66-100) is below real trucking (~USD 200-300).
- Brazil/India/Nigeria/Ghana stack several cascading taxes (ICMS/IPI/PIS, SWS+IGST, CISS/levies); table is a single
  duty + single VAT. Indicative only.
- Road freight: rate per km x 1.15 with a linear partial-load discount; no empty-return, ADR, permit, Turkey->Iraq
  transit-fee or seasonal surcharges. FTL Istanbul->Baghdad market ~USD 3-4.5k (model ~3.2k).
- FCA/FOB: `origin_handling` bundles THC and export clearance; under FCA the split of who pays THC depends on the
  named place. Treated as buyer cost.
- Customs value for DAP/DDP is the supplier price only; many customs administrations deduct destination charges.
- Mock geo (`MockGeo`) has ~35 cities and few hubs; only the real geo dataset gives valid hub choices (e.g. the
  mock routes Riyadh via Umm Qasr). Tests that need realistic routing should use the geo dataset.
- Out-of-scope lint: `.venv/bin/ruff check services scripts` fails only on `services/demand/src/ff_demand/service.py:27`
  (E501, line too long) - owner: demand module.

## Requests
- `docs/requests/logistics-costline-asof.md`: add optional `as_of` and `range` to `CostLine`.
