# Status snapshot - 2026-10-15

A current snapshot, rewritten in place (not a log). History lives in git, `docs/DECISIONS.md` and `docs/decisions/*`.

**Phase position:** Phases 0-3 are done on mock adapters; Phase 4 (real data) is blocked on owner input; Phases 5-6 are built as off-by-default skeletons. See `docs/ROADMAP.md`.

## 1. What exists

**15 backend services** (all behind the gateway, which is the only published port; contracts in `contracts/openapi/*.yaml`, route list in `docs/API_OVERVIEW.md`):
gateway :8000, sourcing, logistics, geo, trust, rfq, messaging, tracking, notifications, assistant, demand, payments, media, feed :8113, freight :8114.

- gateway: auth (refresh rotation, logout, logout-all, token versioning, password reset/change, email verification), supplier claims (admin approval), per-upstream circuit breaker, rate limits (optional Redis), WebSocket tickets, `FF_ENV=production` fail-closed guard, admin passthroughs.
- sourcing: mock + native (supplier-published, bulk import up to 100) + licensed-provider skeleton; bilingual search, facets, recommendations/similar, price history, moderation and reports, HS code finder (~690 indicative codes).
- logistics: landed cost for sea/air/road, duties/VAT (41 countries), FX, carriers, compliance advisor (documents, certificates, incoterms), forwarder quote as a cost override.
- geo (66 countries, ~200 hubs, sea graph), trust (score v2, verification documents with private files, reviews signal), rfq (requests/offers, invite-only requests, deals, deal lifecycle, verified-deal reviews), messaging (REST + WebSocket, attachments, block/mute/archive), tracking (providers skeletons, outbox relay), notifications (alerts, digests, delivery adapters off by default), assistant (rules + cards, optional LLM), demand (public-reply drafts, compliance guards, opt-outs, human approval), payments (mock + USDT-TRC20 skeleton, ledger, signed webhooks), media (re-encoded images, private files with signed URLs), feed (posts, follow, likes, comments), freight (forwarder marketplace: quotes, comparison, award, ratings).

**Admin console** (`apps/admin`, served by the gateway when `FF_GATEWAY_SERVE_ADMIN=true`): supplier claims, moderation, demand drafts, payment events, verification documents (incl. private file viewing), forwarders, feed moderation.

**Mobile app** (Flutter, ar default + en, RTL) features: onboarding, discover/search with facets, listing and supplier pages, trust v2 and verification badge, landed-cost calculator (with awarded forwarder quote), FX, carriers, requests/offers, deals and payment invoices, deal reviews, chat (REST + WebSocket, attachments, block/mute), tracking and shipment alerts, assistant cards, watchlist/alerts/saved searches/compare, feed (posts, follow), freight (requests, quotes, comparison), my products (publish, images, bulk import), analytics, supplier claim and verification, notification prefs, settings (default currency, dark theme, Arabic digits, accessibility), privacy (export/delete account), offline cache and persistence. 32 test files incl. widget smoke tests.

**Data:** 165 listings / 83 suppliers (mock), 25 carriers, duty and freight tables are approximations.

## 2. Verification state

| Area | State |
|---|---|
| Python services | Unit/API tests and ruff green locally on mocks (no network). SQLite in tests. |
| Contracts | `scripts/contract_check.py` (routes) and `scripts/contract_validate.py` (238 responses, 0 drift) run locally and in CI. |
| End to end | `scripts/e2e.py` 35 steps through the gateway (local processes); extended e2e passes. `make compose-e2e` has never been run in a real Docker environment. |
| PostgreSQL 16 | Verified 2026-10-15 (`docs/fixes/postgres-verification-2026-10.md`): all 11 Alembic services upgrade/downgrade/`alembic check` clean; every suite re-run on real PG paths (FOR UPDATE, advisory locks, JSONB); one real bug found and fixed (notifications `mark_alerts_read`). Gateway has no Alembic (create_all only). Not verified: multi-replica concurrency, connection pool, `pg_dump` restore, `FF_ENV=production` + TLS URLs, compose `pg` profile. |
| Flutter app | Never compiled locally (no SDK here). CI only compiles/analyzes/tests and builds a debug APK. `android/` and `ios/` platform folders are not committed (`flutter create .` needed); no real-device run yet. |
| Docker images / compose | `docker compose config` validated only; images never built here. |
| Real providers | Alibaba, freight rates, tracking, TronGrid, FCM/SMTP: skeletons, off by default, wire shapes UNVERIFIED. |
| Supply chain | `docs/fixes/supply-chain-review-2026-10.md`: no secrets in tree, pip-audit clean after raising floors, Docker hardening, workflow permissions. |

## 3. Security reviews

| Round | Scope | Report |
|---|---|---|
| a | Gateway/claims/refresh tokens/CORS (first QA) | `docs/fixes/security-review-2026-10.md` |
| b | Payments ledger race, demand cap, notification email | `docs/fixes/security-review-2026-10-b.md` |
| c | Internal-token fail-open (production guard), is_active re-check | `docs/fixes/security-review-2026-10-c.md` |
| d | Feed, freight, trust verification, private media, licensed feeds, assistant | `docs/fixes/security-review-2026-10-d.md` |
| e | Account deletion/export, analytics, recommendations, trust persistence, CI | `docs/fixes/security-review-2026-10-e.md` |
| f | Assistant, notifications, demand, payments, messaging: caps, erasure, client IP | `docs/fixes/security-review-2026-10-f.md` |
| g | rfq, tracking, geo: invite-only RFQs, refund hides reviews, text sanitising | `docs/fixes/security-review-2026-10-g.md` |
| h | Gateway: password policy/reset, token version, circuit breaker, WS limits | `docs/fixes/security-review-2026-10-h.md` |

Also: `logistics-accuracy-review-2026-10.md`, `media-review-2026-10.md`, `payments-usdt-review-2026-10.md`, `perf-review-2026-10.md`, `mobile-review-2026-10.md`, `contract-drift.md` (resolved), `e2e-extended-findings.md`.

## 4. Open items

### Needs owner input
- Licensed supplier data account (Alibaba Open Platform or licensed provider) and a freight-rate provider; until then everything is mock (Phase 4).
- Run `make compose-e2e` and a real-device APK test on your machine; commit/generate `android/` and `ios/` (mobile P0).
- Production secrets and `FF_ENV=production`, TLS reverse proxy, Postgres URL options (`docs/OWNER_GUIDE.ar.md`, `docs/DEPLOY.md`).
- Product decisions: admin identity (single shared `X-Admin-Token`, no SSO/per-admin tokens); register enumeration (409 `account_exists`); USDT/USD booking policy and reconciliation of unmatched transfers; whether PDFs are accepted for verification; supplier-to-user resolution beyond claims.
- Legal drafts: `docs/PRIVACY_POLICY.draft.md`, `docs/TERMS.draft.md`.

### Needs verification by experts
- Customs broker: duties/VAT tables (41 countries, 2-digit HS rates; US Section 301/IEEPA, Mexico, Brazil/India/Nigeria cascades, Iraq levies not modelled), HS codes, compliance advisor content.
- Freight forwarder: rate table ("approx. rate table v1") and road-freight model vs real quotes on 3 lanes (Phase 4 exit); inland Iraq trucking looks low.
- Live-API checks of unverified wire shapes: TronGrid (confirmations field, block endpoint, pagination), tracking providers, FCM/SMTP.
- Hub coordinates (some unverified); Postgres under real concurrency and pooling.
- Accessibility/RTL on device (RTL send icon, image_picker process death).

### Engineering backlog
- Gateway: bcrypt 72-byte truncation (pre-hash + version marker); require `iss`/`aud` after one refresh TTL; uvicorn flags `--no-server-header --timeout-keep-alive 5` (`docs/requests/gateway-uvicorn-flags.md`); gateway still has no Alembic; WS ticket store in-process unless Redis.
- Per-process state to move to Redis/DB before more than one replica: rate limits (gateway, messaging), assistant quota, sourcing caches.
- Internal-token guard still fails open when `FF_INTERNAL_TOKEN` is unset and `FF_ENV` is not production.
- Freight: ratings need payment/tracking evidence; accept `revision` optional (require in v2). Feed: commenter `user_id` exposed; admin actions on feed/freight have no audit log. Messaging legacy single `attachment` allows any https host unless allow-list set.
- Trust: true uploader check for private verification files (media owner endpoint or HMAC proof, `docs/requests/trust-media-ownership.md`).
- Media: signed URL replay in TTL, byte quota ignores variants, ICC profile dropped, no malware scan, sweeper local-disk only, lower `FF_MEDIA_MAX_PIXELS` on small hosts.
- Sourcing erase job could delete a new claimant's listings on retry (claim epoch needed).
- Payments: reconciliation report for unmatched transfers, `amount` required on confirmed webhooks in v2, `TRUNCATE` revoke on audit tables (deploy docs).
- Logistics: batch geo lookups for cold quotes; JSON blob columns need write-time caps.
- Notifications: price alerts are same-currency only (no FX, no absolute threshold).
- Geo: sea waypoints for Japan, SE Asia, Africa, Black Sea, South America, Australia (`docs/requests/data-geo-sea-nodes.md`).
- Seed data for live mobile tests: approved forwarder, review, analytics events (`docs/requests/mobile-live-seed.md`).
- Supply chain: pin base images by digest and actions by SHA, lock file with hashes, scheduled `pip-audit`, commit `pubspec.lock`, `read_only` containers once on Postgres.
- Cosmetic/ops: gateway sends `X-RateLimit-*` only on 429; no data-consent endpoint beyond export/delete.

## ملخص اليوم (15 أكتوبر)

- **الحساب والجلسات**: إعادة تعيين كلمة المرور، تغيير كلمة المرور بتأكيد الحالية، تسجيل الخروج من كل الأجهزة، وإصدار رقمي للتوكن (token versioning) يُبطل التوكنات القديمة فوراً.
- **المتانة**: قاطع دائرة (circuit breaker) لكل خدمة خلفية في البوابة مع حدود للاتصالات.
- **الطلبات**: طلبات بالدعوة فقط (RFQ للموردين المدعوين)، وتُخفى تقييمات الصفقات المستردة.
- **الموردون**: استيراد جماعي للمنتجات (حتى 100 في المرة)، وعروض أسعار وكلاء الشحن تدخل مباشرة في حساب الكلفة الكاملة.
- **التطبيق**: ذاكرة مؤقتة للعمل دون اتصال، وحظر وكتم المحادثات.
- **الامتثال**: ضوابط مطابقة الطلب العام (demand): مسودات فقط، موافقة بشرية، قوائم رفض، لا رسائل خاصة.
- **الوسائط**: تشديد أمن الصور والملفات الخاصة (إعادة ترميز، روابط موقّعة، إزالة البيانات الوصفية).
- **قاعدة البيانات**: تم التحقق من PostgreSQL 16 فعلياً (ترحيلات + كل الاختبارات) وأُصلح خطأ واحد في الإشعارات.
- **سلسلة التوريد**: فحص أسرار، تدقيق الاعتماديات ورفع الحد الأدنى للإصدارات، تشديد Docker وGitHub Actions.
- **ما زال مطلوباً منك**: حساب API مرخّص لبيانات الموردين، مزوّد أسعار شحن، تجربة التطبيق على هاتف حقيقي و`make compose-e2e`، مراجعة مخلّص جمركي للبيانات، أسرار الإنتاج.
