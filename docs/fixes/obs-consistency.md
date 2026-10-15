# obs.py consistency review

**Status:** findings 2 and 7 FIXED (log-injection hardening ported to all 15 copies, `scripts/check_obs_drift.py` + `make obs-check`, per-service `tests/test_obs_injection.py`). Finding 1 (`/metrics`) still needs an architect decision; 3-6 are informational.

Scope: `services/*/src/*/obs.py` (15 services: assistant, demand, feed, freight, gateway, geo, logistics, media,
messaging, notifications, payments, rfq, sourcing, tracking, trust).

## Findings

1. **No service exposes `/metrics` (or any equivalent).** `obs.py` only provides request logging, `x-request-id`
   propagation, `db_ready` and `ready_response`. `grep -ri metrics services/*/src` finds nothing. Every service has
   `/health` and `/ready` in `main.py`. Decide: either add a shared Prometheus-style `/metrics` (counter + latency
   histogram by service/route template/status, token-protected like other internal routes) or record in
   DECISIONS.md that logs are the only telemetry. Needs an architect decision; not done here.
2. **Log-injection hardening is gateway-only.** `gateway/obs.py` has `_CTRL` and strips CR/LF/U+2028/9 in the
   `FF_LOG_FORMAT=text` formatter. The other 14 copies still print `f"{k}={v}"` raw (the only diff vs gateway is these
   2 lines + 1 import-level constant). Path is a route template and ids are sanitized, so exposure is low, but
   the copies should be re-synced. `ff_common.logs.format_line` has the hardened behaviour and tests.
3. `/ready` differences: `assistant`, `geo`, `logistics`, `sourcing`, `trust` import `ready_response` without `db_ready`
   (no DB; fine). `gateway` additionally probes downstream `/health`.
4. `trust_user_header=False` only in gateway (correct: edge must not trust inbound `x-user-id`). All others trust it
   by default; acceptable only behind the gateway/internal token.
5. Auth exemptions for `/health` and `/ready` are re-implemented per service in `main.py` (feed, freight, media, payments,
   rfq, tracking, trust check both; gateway exempts only `/health` in one middleware). Minor divergence.
6. No redaction pass on log values: obs.py logs only fixed fields (no bodies, queries, headers), so currently safe;
   `ff_common.logs.redact` is available if free-form fields are ever added.
7. Copies are not drift-checked by a test (unlike ratelimit.py). Suggest a test that diffs them after normalising
   the package name.

## py-common additions (this pass)
`money.py` (Decimal-only, half-up, 0/2/3-decimal currencies; IQD zero-decimal to match logistics), `errors.py`
(envelope per `common.schema.json`), `logs.py` (redaction + json/text formats). Fixed during testing: `scaleb`
silently rounded to 28 digits for huge minor-unit values. Note logistics `money.py` `D()` uses `Decimal(str(float))`
and accepts floats; ff_common rejects them.
