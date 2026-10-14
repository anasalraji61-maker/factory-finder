# assistant (port 8109)

Arabic/English natural-language sourcing assistant. `POST /v1/assistant/query {text, locale, destination?}`
-> `{intent, parsed_query, answer_text, listings, quote?, trust?, warnings}`.

* `domain/parser.py` - deterministic rule-based parser (intents search/quote/trust/track/help; kind, condition,
  keywords via bundled glossary, quantity+unit, budget, origin/destination via gazetteer, Arabic-Indic digits,
  container/AWB/IMO refs, `sup_*` ids). Dialect words live in `data/` and `domain/lexicon.py`.
* `clients/` - Protocol + httpx + deterministic mock for sourcing, logistics, trust, tracking(validate).
* `service.py` - orchestration; any downstream failure becomes a `warnings` entry (`<svc>_unavailable`).
* `compose.py` - Arabic (default) / English answer composer; language follows the query text. `llm.py` - optional provider-agnostic `LlmClient` (`MockLlm`, `HttpLlm` = Anthropic Messages shape, base URL configurable); OFF by default.

Tools (intents `shipment_status`, `deal_status`, `compare`, `hs_lookup`; `tools.py`): shipment status by reference (tracking), deal/payment status (rfq; needs `X-User-Id`, otherwise a sign-in notice and no downstream call), compare two `lst_*` listings (sourcing + trust [+ logistics landed cost]), HS-code lookup (logistics). Responses add bilingual `cards[]`. Third-party text is sanitized (`guard.py`, warning `untrusted_text_filtered`). Daily per-user quota (`quota.py`, 429 `quota_exceeded`). Decisions: `docs/decisions/assistant-tools-2.md`.

Run: `uvicorn ff_assistant.main:app --port 8109` (needs `PYTHONPATH=src`). Test: `python -m pytest -q`.

Env (prefix `FF_ASSISTANT_`): `CLIENTS=http|mock`, `SOURCING_URL`, `LOGISTICS_URL`, `TRUST_URL`, `TRACKING_URL`, `RFQ_URL`, `QUOTA_PER_DAY`, `ANON_QUOTA_PER_DAY`,
`HTTP_TIMEOUT_S`, `MAX_LISTINGS`, `LLM=off|mock|anthropic` (default off), `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_TIMEOUT_S`, `LLM_MAX_TOKENS`, `LLM_MIN_CONFIDENCE`, `LLM_REWRITE` (all `FF_ASSISTANT_` prefixed); `FF_INTERNAL_TOKEN`.


## Ops (logging / readiness)
`GET /ready` (unauthenticated, exempt from the internal token): always 200 (no database). Each request emits one JSON log line on stdout (`ts, level, service, request_id, method, path` (route template), `status, duration_ms, user_id`); never query strings, tokens or Authorization. `X-Request-Id` is accepted (safe charset, <=64 chars) or generated and echoed back. `FF_LOG_FORMAT=text` for dev. Code: `obs.py` (self-contained copy).
