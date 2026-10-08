# Architecture — Factory Finder

## 1. Big picture

```
            ┌──────────────────────── Flutter app (apps/mobile) ────────────────────────┐
            │ Discover │ Requests & Offers │ Messages │ Logistics hub │ Profile          │
            └───────────────────────────────┬────────────────────────────────────────────┘
                                            │ HTTPS  /v1/*  (JWT)
                                   ┌────────▼────────┐
                                   │ gateway :8000   │  auth, users, routing, aggregation
                                   └──┬──┬──┬──┬──┬──┘
      ┌───────────────┬──────────────┘  │  │  │  └──────────────┬───────────────────┐
┌─────▼─────┐  ┌──────▼──────┐  ┌──────▼──▼──────┐  ┌────────────▼───┐  ┌────────────▼────┐
│ sourcing  │  │ logistics   │  │ trust :8104    │  │ rfq :8105      │  │ messaging :8106 │
│ :8101     │  │ :8102       │──▶ geo :8103      │  │ tracking :8107 │  │ notifications   │
│ adapters  │  │ landed cost │  │ ports/cities   │  │                │  │ :8108           │
└───────────┘  └─────────────┘  └────────────────┘  └────────────────┘  └─────────────────┘
                         ▲  assistant :8109 orchestrates sourcing + logistics + trust
```

The mobile app talks **only** to the gateway. Services talk to each other over HTTP using the contracts in `contracts/`. Each service owns its data; there are no shared tables.

## 2. Services

| Service | Port | Purpose | State |
|---|---|---|---|
| gateway | 8000 | Auth (JWT), users & profiles, request routing to services, aggregation endpoints | Postgres (users) |
| sourcing | 8101 | Search across supplier sources; normalize listings (product / raw material / production line, new / used) | cache only |
| logistics | 8102 | Landed-cost engine: origin inland → main leg (sea/air/rail/road) → destination port → duties/VAT → destination inland; FX; carriers | stateless (data files) |
| geo | 8103 | Countries, cities, sea ports, airports, land border crossings; nearest-hub lookup; road distance estimates | data files |
| trust | 8104 | Explainable supplier trust score 0–100 with green/yellow/red band | cache only |
| rfq | 8105 | Reverse marketplace: buyer requests, seller offers, deals with commission | Postgres |
| messaging | 8106 | Conversations & messages (REST + WebSocket) | Postgres |
| tracking | 8107 | Shipments by container / B/L / AWB / vessel IMO; normalized event timeline | Postgres |
| notifications | 8108 | Watchlists, price-drop & cheaper-supplier alerts, device push tokens | Postgres |
| assistant | 8109 | Natural-language (Arabic/English) sourcing assistant: text → structured search → one combined answer | stateless |

## 3. Conventions (all Python services)

**Layout**
```
services/<name>/
  pyproject.toml                # deps + [tool.pytest.ini_options] pythonpath=["src"]
  README.md
  src/ff_<name>/
    __init__.py
    main.py                     # app = create_app()
    config.py                   # pydantic-settings, env prefix FF_<NAME>_
    api/                        # FastAPI routers (thin)
    domain/                     # pure business logic (no I/O) — most tests live here
    adapters/                   # external sources/providers: base.py + mock.py + <real>.py
    clients/                    # HTTP clients to OTHER services: Protocol + http + mock
    data/                       # bundled static data (json/csv) when needed
  tests/
```
- Python ≥ 3.12. Dev uses the shared virtualenv at repo root: `.venv/bin/python -m pytest services/<name>`. Do not create other venvs. If you truly need a new package, add it to your `pyproject.toml` and install it with `.venv/bin/pip install <pkg>` (only that package).
- Every service: `GET /health` → `{"status":"ok","service":"<name>","version":"0.1.0"}`; all business routes under `/v1`.
- Error body (every non-2xx): `{"error":{"code":"snake_case_code","message":"human text","details":{}}}`.
- JSON field names are **snake_case**. IDs are strings (`"lst_..."`, `"sup_..."`, `"req_..."` — prefix + ULID/uuid4 hex).
- Money in JSON: `{"amount":"1234.50","currency":"USD"}` — amount is a **decimal string**. Use `Decimal` in Python, never float, for money.
- Countries: ISO-3166 alpha-2 (`CN`, `US`, `DE`, `IQ`). Currencies: ISO-4217. Ports: UN/LOCODE where it exists (`CNSHA`, `IQUQR`).
- Timestamps: ISO-8601 UTC (`2026-10-08T19:00:00Z`).
- Internal auth: the gateway forwards `X-User-Id` and `X-Internal-Token`. Services check the token only when `FF_INTERNAL_TOKEN` is set (unset in dev/tests).
- Persistence: SQLAlchemy 2 (async) with `FF_<NAME>_DATABASE_URL`; default `sqlite+aiosqlite:///./<name>.db`; tests use in-memory SQLite. Tables are created on startup in dev (Alembic later).
- Logging: structured, never log secrets or full user PII.

## 4. Public API (served by each service, exposed by the gateway under the same paths)

**sourcing** — `GET /v1/search` (q, kind=`product|raw_material|production_line`, condition=`new|used|any`, origin_country, category, min_price, max_price, moq_max, verified_only, page, page_size) → `{items:[Listing], total, page, page_size, sources:[{source,status,count}]}` · `GET /v1/listings/{id}` → ListingDetail · `GET /v1/suppliers/{id}` → Supplier · `GET /v1/categories` · `GET /v1/sources`

**logistics** — `POST /v1/quotes/landed-cost` (LandedCostRequest) → LandedCostQuote · `GET /v1/fx/rates?base=USD` · `POST /v1/fx/convert` · `GET /v1/carriers?origin_country=&destination_country=&mode=`

**geo** — `GET /v1/countries` · `GET /v1/cities?country=&q=` · `GET /v1/hubs?country=&type=sea|air|land` · `GET /v1/hubs/nearest?lat=&lon=&type=&limit=` · `GET /v1/distance?from_lat=&from_lon=&to_lat=&to_lon=&mode=road|sea|air`

**trust** — `GET /v1/trust/suppliers/{supplier_id}` → TrustScore · `POST /v1/trust/evaluate` (SupplierSignals) → TrustScore

**rfq** — `POST /v1/requests` · `GET /v1/requests` (mine, status, kind, page) · `GET /v1/requests/{id}` · `POST /v1/requests/{id}/offers` · `GET /v1/requests/{id}/offers` · `POST /v1/offers/{id}/accept` → Deal · `GET /v1/deals/{id}`

**messaging** — `GET /v1/conversations` · `POST /v1/conversations` · `GET /v1/conversations/{id}/messages` · `POST /v1/conversations/{id}/messages` · `POST /v1/conversations/{id}/read` · WS `/v1/ws/conversations/{id}`

**tracking** — `POST /v1/shipments` (reference, reference_type=`container|bl|awb|vessel_imo`, carrier?) · `GET /v1/shipments` · `GET /v1/shipments/{id}` · `POST /v1/shipments/{id}/refresh` · `GET /v1/validate/{reference_type}/{reference}`

**notifications** — `POST /v1/watchlist` · `GET /v1/watchlist` · `DELETE /v1/watchlist/{id}` · `GET /v1/alerts` · `POST /v1/alerts/evaluate` (internal) · `POST /v1/devices`

**assistant** — `POST /v1/assistant/query` `{text, locale, destination?}` → `{intent, parsed_query, answer_text, listings, quote?, trust?}`

**gateway (own)** — `POST /v1/auth/register` · `POST /v1/auth/login` · `POST /v1/auth/refresh` · `GET /v1/me` · `PATCH /v1/me` · `GET /v1/home` (aggregated feed)

Each service writes its OpenAPI in `contracts/openapi/<service>.yaml` and reuses `contracts/schemas/common.schema.json` (`$ref`).

## 5. The landed-cost engine (logistics) — the core differentiator

Input: listing or manual goods (value, quantity, weight kg, volume m³, HS code optional, category), origin (country + city or lat/lon), destination (country + city), incoterm the supplier quoted (EXW / FOB / CIF …), preferred modes.

Steps per transport option (`sea_lcl`, `sea_fcl_20`, `sea_fcl_40`, `sea_fcl_40hc`, `air`, `rail`, `road`):
1. **Origin hub selection** — ask geo for nearest suitable hubs (sea port / airport / rail or land crossing) to the factory; consolidation hubs (e.g. Yiwu, Guangzhou) are considered for LCL.
2. **Origin inland** — road distance × rate per km per vehicle class (by country table) + handling; skipped if incoterm already covers it.
3. **Main leg** — rate provider adapter (mock rate tables per trade lane; real providers later) using chargeable weight (air: max(actual, volume×167 kg/m³); LCL: W/M with 1 m³ = 1000 kg; FCL: container fit by volume/weight).
4. **Destination hub** — best port/airport/border for the destination city (geo), including transshipment notes (e.g. Iraq: Umm Qasr by sea, or via Mersin + truck through Ibrahim Khalil, or Jebel Ali + truck).
5. **Duties & taxes** — estimate from a per-country table (default duty % by HS chapter + VAT/GST + fixed clearance fees). Always returned as an **estimate range** with the rule used.
6. **Destination inland** — road distance from hub to city × local rate.
7. **FX** — every line converted to the buyer's display currency with rate + timestamp.

Output: options sorted by total cost, each with `lines[]` (stage, description, amount, currency, source, estimate flag), `total` (MoneyRange), `transit_days` (min/max), `co2_kg` (optional), `recommended` flag and `warnings[]` (e.g. oversized for LCL, dangerous goods, sanctions/embargo flags for the lane).

## 6. Supplier sources (sourcing adapters)

`base.SourceAdapter` → `search(query) -> list[Listing]`, `get_listing(id)`, `get_supplier(id)`, `health()`.
Adapters: `mock` (rich deterministic catalog: products, raw materials, production lines new & used, origins CN/US/DE/IT/TR…), `alibaba` (official Open Platform API — disabled until keys exist), `made_in_china`, `aliexpress` (affiliate API), `source_1688`, `us_*`, `eu_*` stubs. Real adapters obey CLAUDE.md rule 6 and are off by default. Results from all enabled adapters are merged, de-duplicated, normalized to `Listing`, ranked (relevance, price, trust band).

## 7. Mobile app (apps/mobile)

Package name `factory_finder`. Riverpod + go_router + dio. Arabic RTL default, English second. **No code generation** (hand-written `fromJson`/`toJson`) so it builds anywhere. Shell with 5 bottom tabs:

| Tab | Root path | Owner |
|---|---|---|
| Discover (search, feed, filters, results, listing detail, supplier) | `/discover` | mobile-features-a |
| Requests & Offers (RFQ) | `/requests` | mobile-features-a |
| Messages | `/messages` | mobile-features-b |
| Logistics hub (landed-cost calculator, FX, carriers, tracking) | `/logistics` | mobile-features-b |
| Profile (account, language, currency, watchlist entry) | `/profile` | mobile-core |

Mock mode (`--dart-define=FF_MOCK=true`, default **true**) lets the whole app run without a backend. Exact cross-agent Dart interfaces are specified in `docs/AGENTS.md` §Mobile contract.
