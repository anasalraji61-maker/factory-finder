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

## Known limitations (not fixed, no catalog support)
- `دقيق` also matches "High Precision" CNC (Arabic word is ambiguous: flour / accurate); flour mills rank first.
- Category-only matches still return sibling listings (e.g. `مكيف` -> pumps in the "pumps & air conditioning" category, ranked below).
- No numeric/unit awareness beyond tokens (`250 طن` matches the literal "250"; kg vs كغ vs كغم vs كجم not unified).
- Existing test `test_arabic_query_finds_english_title` relaxed: used bakery lines are legitimately production lines now.
