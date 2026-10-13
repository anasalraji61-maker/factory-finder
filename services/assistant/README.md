# assistant (port 8109)

Arabic/English natural-language sourcing assistant. `POST /v1/assistant/query {text, locale, destination?}`
-> `{intent, parsed_query, answer_text, listings, quote?, trust?, warnings}`.

* `domain/parser.py` - deterministic rule-based parser (intents search/quote/trust/track/help; kind, condition,
  keywords via bundled glossary, quantity+unit, budget, origin/destination via gazetteer, Arabic-Indic digits,
  container/AWB/IMO refs, `sup_*` ids). Dialect words live in `data/` and `domain/lexicon.py`.
* `clients/` - Protocol + httpx + deterministic mock for sourcing, logistics, trust, tracking(validate).
* `service.py` - orchestration; any downstream failure becomes a `warnings` entry (`<svc>_unavailable`).
* `compose.py` - Arabic answer composer. `llm.py` - optional refiner hook (mock default, real adapter stubbed).

Run: `uvicorn ff_assistant.main:app --port 8109` (needs `PYTHONPATH=src`). Test: `python -m pytest -q`.

Env (prefix `FF_ASSISTANT_`): `CLIENTS=http|mock`, `SOURCING_URL`, `LOGISTICS_URL`, `TRUST_URL`, `TRACKING_URL`,
`HTTP_TIMEOUT_S`, `MAX_LISTINGS`, `LLM_PROVIDER=none|mock|anthropic`, `LLM_API_KEY`; `FF_INTERNAL_TOKEN`.
