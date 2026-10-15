# Status — 2026-10-14 night (architect)

**Goal:** Phases 0–3 on mock adapters (done), now hardening before Phase 4 (real data).

## Done
- 10 backend services (gateway, sourcing, logistics, geo, trust, rfq, messaging, tracking, notifications, assistant); all tests + ruff green; `scripts/e2e.py` 22/22 through the gateway.
- Flutter app (ar/en, RTL): discover, listing, supplier, landed-cost calculator, FX, carriers, requests/offers, chat (REST + WebSocket), tracking, assistant, profile, supplier-claim. CI builds a debug APK.
- Security review done: refresh-token rotation, supplier claims need admin approval, CORS off by default, only gateway port published in compose.
- Data: 165 listings / 83 suppliers (mock), 66 countries, ~200 hubs, 41 duty countries, 25 carriers, extended sea graph.

## Added since the first snapshot
- 11 services now (+demand, payments); admin console (apps/admin); WebSocket chat via gateway; Alembic/Postgres support; structured logs + /ready.
- Search: bilingual synonyms, typo tolerance, ranking, facets; HS code finder (~690 indicative codes, verify with a customs broker).
- Mobile: onboarding, persistence, watchlist/alerts, compare, saved searches, trust v2 UI, notification prefs, 120+ tests incl. widget smoke tests.
- Notifications delivery adapters (push/email, off by default); payments (mock + USDT skeleton, ledger, signed webhooks).

- 13 services now (+media). Suppliers can publish their own listings (native source), upload images, verify digest email. Contract validation (132 responses, 0 drift) and e2e (31 steps) in CI.
- Gateway: public image GETs have their own rate bucket (media_rate_limit_per_minute).

- Deal lifecycle: payments -> rfq outbox hook (paid/refunded), fulfilment/delivered/confirm-receipt, event log; mobile deal UI + deals list. Verified-deal reviews (rfq) + mobile UI + trust signal.
- Tracking: real-provider skeletons (off by default), normalization, outbox + relay to notifications (shipment alerts in the app).
- Gateway: email verification, optional Redis rate limits, moderation routes, is_active re-check, FF_ENV=production fail-closed guard. Sourcing: listing moderation + reports. Messaging: media attachments (mobile composer too).
- Backend: 140 responses validated (0 drift), e2e 33 steps; security reviews a/b/c in docs/fixes.
- 14 services (+feed :8113): supplier posts, follow, home/trending feed, likes, comments, reports + admin moderation; routed at /v1/feed/* (see docs/decisions/feed.md). Contract validation 166 responses, e2e 34 steps.
- 15 services (+freight :8114): freight-forwarder marketplace (forwarder application + admin approval, shipment quote requests, lane-matched quotes, explainable ranking, idempotent award, ratings, reports + admin moderation); routed at /v1/freight/* (see docs/decisions/freight.md). Contract validation 238 responses, e2e 35 steps.

## Next (needs owner input)
- Phase 4: official supplier API account (Alibaba or licensed provider) and a freight-rate provider; until then all data is mock.
- Real-device test of the APK (Flutter never compiled locally; CI is the only check).

## Known gaps
- Rate limiting is per-IP in-memory; direct service ports trust X-User-Id when FF_INTERNAL_TOKEN is unset (private network only).
- Duty and freight tables are approximations; some hub coordinates unverified; some sea regions missing (see docs/requests/data-geo-sea-nodes.md).
- Admin approval of supplier claims has no UI (HTTP endpoints only).

## ملخص الصباح (15 أكتوبر) — بالعربي
- الخدمات الآن 15: أُضيفت **feed** (منشورات الموردين/متابعة/إعجاب/تعليقات) و**freight** (وكلاء الشحن: عروض أسعار ومقارنة وترسية).
- **صفقات**: دورة حياة كاملة (دفع ← تنفيذ ← تسليم ← استلام) + تقييمات للموردين تدخل في درجة الثقة.
- **توثيق الموردين**: رفع وثائق (ملفات خاصة بروابط موقّعة) + مراجعة الإدارة + شارة مستوى التوثيق.
- **مستشار الامتثال الجمركي** (العراق والخليج وتركيا...): مستندات مطلوبة وشهادات مطابقة وإنكوترمز — بيانات تقريبية تُراجع مع مخلّص جمركي.
- **المساعد الذكي** يعرض بطاقات (شحنة/صفقة/مقارنة/رمز جمركي). حساب الكلفة أسرع ~18 ضعفاً.
- الأمان: 4 جولات مراجعة (a–d)، حماية الإنتاج (FF_ENV=production)، تحقق البريد، Redis اختياري للحدود.
- التطبيق: إعدادات (دينار افتراضي، مظهر داكن، أرقام عربية)، إمكانية وصول، وضع عدم الاتصال، منشورات، وكلاء شحن، صفقات، توثيق.
- لوحة الإدارة: إشراف، مدفوعات، توثيق، شحن، منشورات، عرض الوثائق الخاصة.
- ما زال يحتاج منك: حساب API مرخّص لبيانات الموردين، مزوّد أسعار شحن، تشغيل `make compose-e2e` على جهازك، مراجعة مخلّص جمركي للبيانات، أسرار الإنتاج (انظر docs/OWNER_GUIDE.ar.md).
- (تحديث 15 أكتوبر صباحاً) جولة أمنية f: حدود احتفاظ وحجم في الدفع والمراسلة والإشعارات والطلب، حذف نص الرسائل عند مسح المستخدم، حماية الـ webhook، مراجعة دقة الكلفة اللوجستية (تسعير الشاحنة، افتراضات صريحة)، IP العميل للمساعد عبر البوابة. المفتوح: محددات المعدل داخل العملية، بيانات الجمارك تحتاج مخلّصاً.
