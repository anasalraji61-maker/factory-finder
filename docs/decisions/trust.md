- 2026-10-13 | Score = clamp(baseline 40 + sum(round(weight*f)),0,100) then hard caps; each signal f in [-1,1] with saturating curves | explainable, sums reconcile with factors list.
- 2026-10-13 | Bands green>=75, yellow 50-74, red<50; unknown if <4 known signals (sanctions hit overrides to red) | avoid false verdicts on thin data.
- 2026-10-13 | Caps: sanctions<=20; dispute_rate>=0.08 -> <=69, >=0.15 -> <=49; price/market<0.4 -> <=59 | scam heuristics; cap factors carry negative impact so factors still sum to the score.
- 2026-10-13 | Unknown supplier id in mock adapter yields hash-derived signals (never 404); real adapters are disabled stubs returning 503 adapter_disabled | spec requirement.
- 2026-10-13 | Batch response is {items:[TrustScore]} (unknown ids omitted); extra optional fields confidence/model_version added to TrustScore (additive).
2026-10-15 trust: added deal_cancellation_cap (cancel share >=30%/50% with >=20 deals caps 69/59); a bounded -4 factor let a mostly-cancelling supplier stay green
