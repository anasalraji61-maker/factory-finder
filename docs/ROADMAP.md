# Roadmap

Each phase closes only when its exit criteria pass QA. Waves inside a phase run agents in parallel.

| Phase | Goal | Exit criteria |
|---|---|---|
| **0 — Foundation** | Repo skeleton, contracts, CI, dev environment | `make test` green; CI green; every service answers `/health` |
| **1 — Core MVP (China → any country)** | Search (mock + China source stubs), landed-cost engine for all modes, geo data, trust score v1, app shell with Discover + Logistics calculator | Search → listing → landed-cost to Baghdad/Istanbul/Dubai/Berlin returns sane, explained options; app runs fully in mock mode |
| **2 — Marketplace** | Requests & offers (reverse marketplace), deals with commission, in-app messaging | Buyer posts a request, supplier offers, buyer accepts, deal + commission recorded; chat works over WebSocket |
| **3 — Retention** | Shipment tracking, watchlist & price alerts, Arabic AI assistant | Track a container end-to-end (mock provider); alert fires on price drop; assistant answers "أريد خط إنتاج معجنات مستعمل من الصين يوصل بغداد" with listings + cost |
| **4 — Real data & more origins** | First real supplier source via official API/licensed provider; real freight & FX providers; origins USA then Europe | Real results for one category; quotes within ±15% of a forwarder quote on 3 lanes |
| **5 — Demand matching** | Detect public buy-requests (e.g. Facebook groups), prepare matched offers, publish public replies with human-in-the-loop and strict volume limits | 20 matched replies/day without account warnings; conversion tracked |
| **6 — Payments & launch** | Crypto checkout (USDT) first; card payments after the UK company + Payoneer/Stripe; commission settlement; store release | First paid commission collected; app on Play Store / App Store (TestFlight) |

Wave 1 builds Phases 0–3 in parallel against mock adapters. Phases 4–6 replace mocks with real providers.
