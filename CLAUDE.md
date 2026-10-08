# CLAUDE.md — Factory Finder (مُوَرِّد)

> **ملخص بالعربي:** منصة عالمية ذكية للتوريد: تبحث عن المنتجات والمواد الأولية والخطوط الإنتاجية (جديدة ومستعملة)، تتحقق من مصداقية المورد، وتحسب الكلفة الكاملة لحد باب الزبون (شحن داخلي ← بحري/جوي/بري ← جمارك ← نقل داخلي) لأي دولة بالعالم. البداية من الصين، ثم أمريكا، ثم أوروبا.
> هذا الملف هو "القائد" — كل وكيل يقرأه أولاً ويلتزم به حرفياً.

This file is the single source of truth for every agent working in this repo. Read it fully before touching code. Then read `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, and **your own brief** in `docs/AGENTS.md`.

---

## 1. Product in one paragraph

A cross-platform (Android + iOS) sourcing app, social-media style (Alibaba × Facebook × Instagram). A buyer anywhere in the world searches for a **product, raw material, or production line (new/used)**. The platform finds suppliers across sources (China first: Alibaba, 1688, Made-in-China, AliExpress; later US and Europe), scores each supplier's **trustworthiness**, and computes the **full landed cost to the buyer's city**: origin inland haul → main leg (sea / air / land) → destination port/border → duties & taxes estimate → destination inland haul, all converted with live FX. Buyers can also post a **request** (reverse marketplace) and receive offers. The platform earns **commission** as the intermediary.

## 2. Non-negotiable rules for every agent

1. **Modular, always.** Each module lives in its own directory and owns its own code, tests and README. Modules talk to each other **only through the contracts in `contracts/`** (OpenAPI + JSON Schema). Never import another module's internals.
2. **Stay in your lane.** Only edit files inside the directory your brief assigns you, plus adding *new* files under `contracts/` when your brief allows it. Need a change in someone else's module or an existing contract? Write it in `docs/requests/<your-module>-<topic>.md` and continue with a mock.
3. **Contracts first.** Before implementing an endpoint, its schema must exist in `contracts/`. Changing an existing contract = additive only (new optional fields). Breaking changes require a new version (`/v2`).
4. **Every source / provider is an adapter.** Supplier sources, freight rate providers, FX providers, tracking providers, and LLM providers all sit behind an interface with at least: a real adapter (may be stubbed) and a **deterministic mock adapter**. All tests run against mocks — no network in tests.
5. **No secrets in the repo — it is PUBLIC.** Keys come from environment variables only. Commit `.env.example` with empty values. Never print, log, or commit a key.
6. **Data sourcing must be lawful.** Prefer official APIs and licensed data providers. Any adapter that reads public web pages must: respect `robots.txt` and the site's terms, rate-limit (default ≤ 1 req / 3 s per host), cache aggressively, identify itself honestly, and be switchable off by config. Never bypass CAPTCHAs, logins or paywalls.
7. **Social platforms (Facebook etc.):** no automated private messaging of strangers. The demand-matching feature (Phase 5) only drafts public replies and enforces low daily volume; a human-in-the-loop switch exists.
8. **Money & numbers are exact.** Use `Decimal` (Python) / integer minor units for money. Every cost line carries its currency, source, and timestamp. Estimates are labeled as estimates with a range.
9. **Arabic-first, RTL-correct UI**, with English as the second language. All user-facing strings go through i18n files — no hardcoded text in widgets.
10. **Tests or it didn't happen.** Every PR adds/updates tests. `make test` must pass at the repo root before a phase is closed.
11. **Work autonomously.** Do not stop to ask for permission. When something is ambiguous, pick the simplest reasonable option, write the decision in `docs/decisions/<your-agent-id>.md` (one line: date, decision, why) and continue. Cross-cutting decisions live in `docs/DECISIONS.md` (architect only).
12. **Builders build, reviewers review.** Builders never mark their own work as verified. QA agents (see `docs/AGENTS.md`) run after the builders of a wave have finished; they run tests, review, and fix problems in place. Anything they cannot fix goes to `docs/fixes/<topic>.md` and blocks the phase until fixed.
13. **Git is the orchestrator's job.** Agents never commit, push, branch or reset.

## 3. Tech stack (decided)

| Layer | Choice |
|---|---|
| Mobile app | Flutter (Dart), Riverpod for state, go_router, `flutter_localizations` (ar default, en) |
| Backend services | Python 3.12, FastAPI, Pydantic v2, httpx |
| Database | PostgreSQL (SQLAlchemy 2 + Alembic); SQLite allowed in tests |
| Cache / queue | Redis (optional in dev; in-memory fallback) |
| Background jobs | Python worker (arq or simple asyncio loop) |
| AI | Provider-agnostic `llm` adapter (mock + real), small/cheap model by default |
| Contracts | OpenAPI 3.1 (`contracts/openapi/*.yaml`) + JSON Schema (`contracts/schemas/*.json`) |
| CI | GitHub Actions: lint + tests for every module |
| Dev | `docker-compose.yml` at root; `make dev`, `make test`, `make lint` |

## 4. Repository map

```
apps/mobile/            Flutter app (UI shell + 5 tabs)
services/gateway/       API gateway: auth, users, routing to services
services/sourcing/      Search across supplier sources (adapters)
services/logistics/     Landed-cost engine: routes, freight, duties, FX
services/trust/         Supplier trust score
services/rfq/           Reverse marketplace: buyer requests & seller offers
services/messaging/     In-app conversations
services/tracking/      Shipment tracking (container / AWB / vessel)
services/notifications/ Price-drop & opportunity alerts
packages/py-common/     Shared Python utils (money, errors, logging) — no business logic
contracts/              OpenAPI + JSON Schemas (the only shared interface)
docs/                   Architecture, roadmap, agent briefs, decisions, fixes
infra/                  docker-compose, CI, deployment
```

## 5. Definition of Done (per task)

- Code inside your assigned directory only
- Contract exists and matches implementation
- Unit tests + at least one contract test pass locally
- Module README updated (what it does, how to run, env vars)
- No secrets, no network in tests, lint clean
- Commit message: `<module>: <what>` (e.g. `logistics: sea freight route estimator`)

## 6. Where to look next

- `docs/ARCHITECTURE.md` — modules, data flow, contracts
- `docs/ROADMAP.md` — phases and exit criteria
- `docs/AGENTS.md` — agent roster, ownership, and copy-paste launch prompts
- `docs/DECISIONS.md` — decision log (append-only)
