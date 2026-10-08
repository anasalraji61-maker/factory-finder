# Decision log (architect)

Agents record their own decisions in `docs/decisions/<agent-id>.md`. This file holds cross-cutting decisions only.

| Date | Area | Decision | Why |
|---|---|---|---|
| 2026-10-08 | Stack | Flutter app + Python/FastAPI microservices + Postgres | One codebase for Android & iOS; Python is strongest for data/AI/scraping work |
| 2026-10-08 | Modularity | One directory per service/feature, contracts-only coupling | Lets 10+ agents build in parallel and lets any module be replaced later |
| 2026-10-08 | Shared code | No shared Python package in wave 1 | Avoids cross-agent blocking; extract common helpers later |
| 2026-10-08 | Mobile codegen | No code generation (hand-written JSON) | Builds without build_runner; the build sandbox has no Flutter SDK |
| 2026-10-08 | Data sourcing | Official APIs / licensed providers first; any web reading must respect robots/ToS, be rate-limited and switchable off | Legal safety and account safety |
| 2026-10-08 | Launch order | Origins: China → USA → Europe; destinations: worldwide | Owner's priority |
| 2026-10-08 | Money | Decimal strings in JSON, Decimal in Python | No float rounding errors in quotes |
