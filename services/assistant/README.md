# assistant (port 8109)

Arabic/English natural-language sourcing assistant. `POST /v1/assistant/query {text, locale, destination?}`
-> `{intent, parsed_query, answer_text, listings, quote?, trust?, warnings}`.

* `domain/parser.py` - deterministic rule-based parser (intents search/quote/trust/track/help; kind, condition,
  keywords via bundled glossary, quantity+unit, budget, origin/destination via gazetteer, Arabic-Indic digits,
  container/AWB/IMO refs, `sup_*` ids). Dialect words live in `data/` and `domain/lexicon.py`.
* `clients/` - Protocol + httpx + deterministic mock for sourcing, logistics, trust, tracking(validate).
* `service.py` - orchestration; any downstream failure becomes a `warnings` entry (`<svc>_unavailable`).
* `compose.py` - Arabic (default) / English answer composer; language follows the query text. `llm.py` - optional provider-agnostic `LlmClient` (`MockLlm`, `HttpLlm` = Anthropic Messages shape, base URL configurable); OFF by default.

Multilingual routing: Turkish, Kurdish (Sorani), Persian and simple Chinese share the same lexicon structure (`domain/lexicon_ml.py`, `data/aliases_ml.json`; Chinese is segmented by `domain/han.py`, Turkish apostrophe suffixes become direction markers in `text.py`). Replies use the Arabic/English templates (Arabic-script input -> Arabic; Latin/Chinese -> English).

Tools (intents `shipment_status`, `deal_status`, `compare`, `hs_lookup`; `tools.py`): shipment status by reference (tracking), deal/payment status (rfq; needs `X-User-Id`, otherwise a sign-in notice and no downstream call), compare two `lst_*` listings (sourcing + trust [+ logistics landed cost]), HS-code lookup (logistics). Responses add bilingual `cards[]`. Third-party text is sanitized (`guard.py`, warning `untrusted_text_filtered`). Daily per-user quota (`quota.py`, 429 `quota_exceeded`). Decisions: `docs/decisions/assistant-tools-2.md`.

Run: `uvicorn ff_assistant.main:app --port 8109` (needs `PYTHONPATH=src`). Test: `python -m pytest -q`.

Env (prefix `FF_ASSISTANT_`): `CLIENTS=http|mock`, `SOURCING_URL`, `LOGISTICS_URL`, `TRUST_URL`, `TRACKING_URL`, `RFQ_URL`, `QUOTA_PER_DAY`, `ANON_QUOTA_PER_DAY`,
`HTTP_TIMEOUT_S`, `MAX_LISTINGS`, `LLM=off|mock|anthropic` (default off), `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_TIMEOUT_S`, `LLM_MAX_TOKENS`, `LLM_MIN_CONFIDENCE`, `LLM_REWRITE` (all `FF_ASSISTANT_` prefixed); `FF_INTERNAL_TOKEN`.


## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): always 200 (no database). Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).

## Environment reference (complete)
Every setting in `src/ff_assistant/config.py` (`Settings`, case-insensitive env names; empty values count as unset). Secrets are never defaulted.

| Variable | Default |
|---|---|
| `FF_ASSISTANT_CLIENTS` | http |
| `FF_ASSISTANT_SOURCING_URL` | http://localhost:8101 |
| `FF_ASSISTANT_LOGISTICS_URL` | http://localhost:8102 |
| `FF_ASSISTANT_TRUST_URL` | http://localhost:8104 |
| `FF_ASSISTANT_TRACKING_URL` | http://localhost:8107 |
| `FF_ASSISTANT_RFQ_URL` | http://localhost:8105 |
| `FF_ASSISTANT_HTTP_TIMEOUT_S` | 4.0 |
| `FF_INTERNAL_TOKEN` / `FF_ASSISTANT_INTERNAL_TOKEN` | unset |
| `FF_ASSISTANT_TRUST_CLIENT_IP_HEADER` | False |
| `FF_ASSISTANT_DEFAULT_CURRENCY` | USD |
| `FF_ASSISTANT_MAX_LISTINGS` | 3 |
| `FF_ASSISTANT_SEARCH_PAGE_SIZE` | 10 |
| `FF_ASSISTANT_QUOTA_PER_DAY` | 200 |
| `FF_ASSISTANT_ANON_QUOTA_PER_DAY` | 30 |
| `FF_ASSISTANT_LLM` | off |
| `FF_ASSISTANT_LLM_API_KEY` | unset |
| `FF_ASSISTANT_LLM_MODEL` | claude-haiku-5-5 |
| `FF_ASSISTANT_LLM_BASE_URL` | https://api.anthropic.com |
| `FF_ASSISTANT_LLM_TIMEOUT_S` | 6.0 |
| `FF_ASSISTANT_LLM_MAX_TOKENS` | 300 |
| `FF_ASSISTANT_LLM_MAX_INPUT_CHARS` | 1500 |
| `FF_ASSISTANT_LLM_MIN_CONFIDENCE` | 0.5 |
| `FF_ASSISTANT_LLM_REWRITE` | False |

Also read from the environment: `FF_LOG_FORMAT` (`text` for dev; JSON by default).

Quota counters use `ratelimit.py` (self-contained copy of `packages/py-common/src/ff_common/ratelimit.py`), UTC-day window. In-memory by default; set `FF_REDIS_URL` (or `FF_ASSISTANT_REDIS_URL`; needs `pip install ff-assistant[redis]`) to share them across replicas. Redis outage falls back to per-process counting with a warning.
