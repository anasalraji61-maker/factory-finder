# Sourcing relevance QA (2026-10-15)

Method: ~100 bilingual buyer queries (raw materials, machines, used lines, packaging, textiles, Iraqi-dialect items,
misspellings, tashkeel/hamza/ى/ة variants, units طن/كغم, kind/condition/MOQ filters, price/MOQ sorts) run against the
165-listing mock catalog. 60+ kept as the regression fixture `services/sourcing/tests/fixtures/relevance_cases.json`,
run by `services/sourcing/tests/test_relevance.py` (top1 / top-5 / total / kind+condition / MOQ / sort order /
spelling-variant equivalence).

## Defects found and fixed
- `خط انتاج مستعمل` / `used production line` returned 0: kind and condition were not searchable. Kind and condition
  words now count as category-level (0.6) text (`search._KIND_TEXT`, `_CONDITION_TEXT`).
- Arabic sound plurals missed singulars (`اطار سيارة` -> only a battery; سيارات vs سيارة): `stem()` maps trailing `ات` -> `ه`.
- Two words of one synonym group (`مكيف سبلت`, `كاميرا مراقبة`) were AND-ed as two terms and matched anything in the category:
  `parse_query` now keeps one term per group.
- Over-broad groups split: `ابلكاش` (plywood) no longer matches every wood/panel listing; `مخرطة` (lathe) no longer returns
  machining centers; `كرتون مموج` no longer returns a strapping line; `مضخة ماء` is its own "water pump" group (it returned
  cosmetic pump bottles and AC units); `كاميرا مراقبة` is its own CCTV group; removed `ماكنة حقن` shortcut that skipped the
  "machine" term.
- Iraqi `طابوق` meant clay brick but resolved to concrete block; now brick (`بلوك` stays concrete block).
- Missing vocabulary: stainless (`ستانلس`), coil/roll (`لفة`, `رول`), sheet (`شيت`), `بيت`/`بي اي تي` = PET, blow/blowing,
  `حديد بناء`, `مولد كهرباء`, `جينز`, `تايلز`, `مقسى`, `نسائي`, `مجدد`, `فلم`.
- Ranking: supplier-name / boilerplate-description-only hits (relevance < 0.4) are dropped when real title/category hits
  exist (`prune_weak`), so `كاميرا` no longer lists chargers from "Visionguard Electronics". Synonym-aware phrase boost
  (`synonym_phrase`, either order) so Arabic noun-adjective order boosts the English title.
- Demand (`ff_demand.intent`): buy-intent detection and lead-word stripping now ignore tashkeel/tatweel and أ/إ/آ, ى, ة
  variants; added `ابغي/ابغى/بدي/عايز`. Query keeps the user's spelling (tashkeel removed).

## Former limitations, now addressed
- Units: `text.tokens()` maps kg/kgs/kilo/كغ/كغم/كجم/كيلو, ton/tonne/mt/طن, m/meter/متر, l/litre/لتر, pc/pcs/piece/قطعة to one
  canonical token and splits `250kg/h` / `250كغم` into number + unit (bare `l` is never split off: steel grades 304L).
- `دقيق` vs "High Precision": ambiguous words (`search._AMBIGUOUS`) score x0.35 when they are the only hit, so the
  weak-hit prune drops them once real flour listings exist.
- `مكيف` vs pumps: `Match.sibling` marks hits reached only through a secondary segment of a compound category label;
  `prune_weak` drops them when title hits exist (`pump` still lists its own category).
- Latency guard: `test_search_latency_p95_regression` (p95 of 200 mixed queries < 500 ms).

## Remaining limitations
- No numeric-range/magnitude awareness (`250 طن` still matches the literal 250 plus unit token, not "about 250").
- Existing test `test_arabic_query_finds_english_title` relaxed: used bakery lines are legitimately production lines now.
