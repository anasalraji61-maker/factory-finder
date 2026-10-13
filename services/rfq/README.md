# rfq (port 8105)

Reverse marketplace: buyers post requests (product / raw material / production line), suppliers send offers,
the buyer accepts one and a Deal with platform commission is created.

- Run: `uvicorn ff_rfq.main:app --port 8105`; tests: `../../.venv/bin/python -m pytest -q`
- Contract: `contracts/openapi/rfq.yaml`. `X-User-Id` required on `/v1` (missing -> 401); `X-Internal-Token` checked only when `FF_INTERNAL_TOKEN` is set.
- Status machines in `domain/state.py`; commission in `domain/commission.py` (Decimal, half-up cents; min fee in USD converted with static reference rates).
- Expiry is lazy: deadlines / offer validity are evaluated on each call.
- Suggestions come from sourcing through `clients/sourcing.py` (httpx + deterministic mock; tests use the mock).

| Env | Default |
|---|---|
| `FF_RFQ_DATABASE_URL` | `sqlite+aiosqlite:///./rfq.db` |
| `FF_RFQ_SOURCING_URL` | `http://localhost:8101` |
| `FF_RFQ_SOURCING_CLIENT` | `http` (or `mock`) |
| `FF_RFQ_COMMISSION_PRODUCT` / `_RAW_MATERIAL` / `_PRODUCTION_LINE` | `0.03` / `0.02` / `0.04` |
| `FF_RFQ_MIN_COMMISSION_USD` | `25` |

Offer identity: owner = `X-User-Id`; `supplier_ref` = gateway-verified `X-Supplier-Id` (else null, `supplier_verified=false`). A `supplier_ref` in the request body is ignored; `supplier_name` is a display label only.
