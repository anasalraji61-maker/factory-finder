# trust (port 8104)

Explainable supplier trust score 0-100 with band green (>=75) / yellow (50-74) / red (<50) / unknown (<4 known signals). Hard caps: sanctions hit -> red, <=20; dispute rate >=8% -> <=69, >=15% -> <=49; price < 0.4x market -> <=59. Every factor has a signed integer impact plus `explanation` / `explanation_ar`.

Endpoints: `GET /v1/trust/suppliers/{id}` (TTL cache), `GET /v1/trust/suppliers:batch?ids=a,b`, `POST /v1/trust/evaluate`, `GET /health`. Contract: `contracts/openapi/trust.yaml`.

Run: `uvicorn ff_trust.main:app --port 8104`. Test: `../../.venv/bin/python -m pytest -q`.

Env: `FF_TRUST_ADAPTER` (mock default; alibaba/made_in_china are disabled stubs), `FF_TRUST_CACHE_TTL_SECONDS` (300), `FF_TRUST_MAX_BATCH` (50), `FF_INTERNAL_TOKEN` (optional).
Mock ids: any id works (sha256-derived); curated `sup_demo_gold|avg|scam|sanctioned`.
