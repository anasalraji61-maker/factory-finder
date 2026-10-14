# Decision: generic licensed REST provider adapter (sourcing)

2026-10-14 - Added `adapters/licensed_rest.py` (declarative JSON mapping on top of `HttpProviderAdapter`) plus `domain/quality.py` and the `python -m ff_sourcing.licensed_validate` CLI. Why: the owner can plug in any licensed/official supplier-data API without code, while rule 6 compliance (>= 3 s/host, cache, kill switch, honest UA, no bypass, official API only) is enforced centrally rather than per provider.

Other decisions (one line each):
- GET only, https only, no credentials in URL/templates; keys only via env var NAMES in `auth.key_env` (header | query | bearer). Validator rejects key-like literals.
- Mapping must carry `tos_note` and `robots_note`; example files are `example: true`, fictional `.invalid` hosts, and refused at runtime unless `FF_SOURCING_LICENSED_ALLOW_EXAMPLE` is set.
- Loaded adapters are registered but enabled only when their id is also in `FF_SOURCING_ADAPTERS`; a bad mapping is logged and skipped, never breaks startup.
- Failure (HTTP error, 401/403/429, kill switch, timeout) falls back to mock with a `warning` in `sources[]` (existing SourcingService behaviour). Page 2+ failure keeps partial results.
- `max_pages > 1` costs >= 3 s per extra page; service per-adapter timeout is 3 s by default, so raise `FF_SOURCING_ADAPTER_TIMEOUT_S`. Default is 1 page.
- Quality: items with non-positive/absurd prices (ratio > `max_ratio`, outside bounds) or disallowed currency are dropped; same-supplier near-duplicate titles (order-insensitive similarity >= 0.9, same currency) collapse to the richest one. Images not on `images.allowed_hosts` (https) are dropped. No contract change needed (listing shape unchanged).
- Unverified against any live provider: mappings are the owner's responsibility; validate with `--sample` against a recorded response first.

## Owner: enabling a provider
1. Copy an example from `services/sourcing/examples/licensed/` outside the repo (or to a git-ignored path), set `id`, `base_url`, `auth`, `request`, `items_path`, `fields`, `tos_note`, `robots_note`, `images.allowed_hosts`; set `"example": false`.
2. Validate: `.venv/bin/python -m ff_sourcing.licensed_validate my.mapping.json --sample recorded_response.json` (run from `services/sourcing/src`, or with the package installed).
3. Set in your private `.env`: `FF_SOURCING_<YOUR_KEY_ENV>=<key>`, `FF_SOURCING_LICENSED_MAPPINGS=/path/my.mapping.json`, `FF_SOURCING_ADAPTERS=<id>`.
4. Check `GET /v1/sources` shows the source; kill instantly with `FF_SOURCING_KILL_SWITCH=1` or the mapping's `kill_switch_env`.
