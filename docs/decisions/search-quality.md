# search-quality decisions

- 2026-10-14: Typo tolerance is rule-guarded (same first letter, len >= 4, no 4-letter substitutions, no digits, distance <= 1, or 2 for >= 8 letters) instead of a plain edit distance, because tile/tire, pipe/pine style false positives hurt a sourcing catalog more than a missed typo.
- 2026-10-14: Doc-side fuzzy matching is applied only to words unknown to the synonym table (synonym-resolved terms are exact), to keep search at ~5-12 ms for 165 listings and avoid cross-group noise.
- 2026-10-14: Chinese is tokenised per character and matched via phrase synonyms (no segmenter dependency); unknown Chinese words simply do not match.
- 2026-10-14: Weights moved to relevance 0.62 / phrase 0.10 / trust 0.12 / verified 0.03 / price 0.13 so trust is a small boost, not a driver; `sort` is a request-only argument (not part of SearchQuery) so it does not fragment the adapter result cache.
- 2026-10-14: Mock adapter returns shared read-only listings and the service shallow-copies kept ones (deep copies of the 165-item catalog dominated latency); `_enrich` only rebinds `.supplier`.
- 2026-10-14: `facets` is a new optional response field (additive); counts follow the filtered, matched set before pagination.
