# دليل المالك — مُوَرِّد (Factory Finder)

كُتب هذا الدليل لك (أنس) وليس للمبرمجين. كل شيء هنا مأخوذ من الكود والوثائق الموجودة في المستودع. حيث لا نعرف أو لم نتحقق، كتبنا "تحقق" ولم نخترع أرقاماً. الأوامر والأسماء التقنية تبقى بالإنكليزية كما هي.

آخر تحديث للحالة: 2026-10-15. للتفاصيل التقنية: `docs/STATUS.md` و`docs/DEPLOY.md` و`docs/RUNBOOK.md` و`docs/API_OVERVIEW.md`.

---

## 1) ما الموجود اليوم؟

منصة توريد: المشتري في أي دولة يبحث عن منتج أو مادة أولية أو خط إنتاج (جديد/مستعمل)، فيرى الموردين مع تقييم الثقة، ويحسب النظام الكلفة الكاملة حتى باب المشتري (شحن داخلي، بحري/جوي/بري، جمارك، نقل داخلي)، ويمكنه نشر طلب وتلقي عروض، والدردشة، وتتبع الشحنة، ومساعد ذكي بالعربي.

الموجود فعلياً:
- 15 خدمة خلفية (بوابة gateway + sourcing + logistics + geo + trust + rfq + messaging + tracking + notifications + assistant + demand + payments + media + feed + freight).
- تطبيق موبايل Flutter (عربي RTL أولاً، إنكليزي ثانياً): اكتشاف، صفحة منتج، صفحة مورد، حاسبة الكلفة الكاملة، أسعار الصرف، الطلبات والعروض، الصفقات، الدردشة، التتبع، المساعد، قائمة المراقبة والتنبيهات، تسجيل الدخول، مطالبة المورد بحسابه.
- لوحة إدارة بسيطة (`apps/admin`): الموافقة على مطالبات الموردين، مراجعة الإبلاغات وإخفاء الإعلانات، مسودات الرد (demand)، متابعة أحداث الدفع، مراجعة وثائق توثيق الموردين، والموافقة على وكلاء الشحن (freight) وإدارة المنشورات (feed).
- اختبارات آلية وفحص end-to-end عبر البوابة في GitHub Actions.

## 2) ما هو وهمي (Mock) وما هو حقيقي؟

| الجزء | الوضع اليوم |
|---|---|
| الموردون والمنتجات (165 إعلان / 83 مورد) | **وهمي** (بيانات تجريبية). الحقيقي الوحيد: إعلانات ينشرها موردون داخل المنصة نفسها ("native") وصورها. |
| الاتصال بعلي بابا/1688/Made-in-China/AliExpress | **غير مفعّل**. يوجد هيكل (skeleton) لواجهة Alibaba Open Platform لم يُجرَّب على خدمة حقيقية. |
| أسعار الشحن | **جداول تقريبية مدمجة**. موفّر أسعار حقيقي (`http`) موجود كهيكل غير مجرَّب. |
| الجمارك/الضرائب (41 دولة) والرموز الجمركية HS (~690) | **تقديرية**. تحقق مع مخلّص جمركي قبل أي قرار مالي. |
| أسعار الصرف | وهمية افتراضياً؛ خيار `ecb` مجاني (frankfurter.dev) بدون مفتاح. |
| الدول والمدن والموانئ (66 دولة، ~200 مركز) | بيانات مجمّعة داخل المشروع، بعض الإحداثيات غير مؤكدة. |
| درجة الثقة | تُحسب من إشارات؛ المصادر الخارجية للتحقق (عقوبات، شهادات) **وهمية**. |
| تتبع الشحنات | وهمي. هياكل لمزودين حقيقيين (حاويات، AWB، سفن) موجودة وغير مفعّلة. |
| الإشعارات (Push/Email) | الإرسال **مطفأ** افتراضياً. هيكل FCM وSMTP موجود. التطبيق نفسه **لا يحوي بعد** مكتبة Firebase، أي لن تصله إشعارات Push قبل إضافتها. |
| الدفع | وهمي (`mock`). هيكل USDT على شبكة TRON موجود ولم يُجرَّب على الشبكة. لا يوجد دفع بالبطاقات. |
| المساعد الذكي | قواعد وكلمات مفتاحية. نموذج لغوي خارجي (Anthropic) اختياري ومطفأ. |
| مطابقة الطلب العام (demand، مثل فيسبوك) | مسودات فقط، **مطفأة** افتراضياً، وتحتاج موافقة بشرية. لا رسائل خاصة آلية أبداً. |
| بناء التطبيق | لم يُبنَ Flutter على جهاز المطور قط. الفحص الوحيد هو GitHub Actions. **لم يُجرَّب على هاتف حقيقي بعد.** |
| docker compose | الإعدادات سليمة نظرياً لكن **لم ينجح أي تشغيل فعلي** لأن بيئة الاختبار لم تستطع تنزيل صورة python من Docker Hub. أول تشغيل على جهازك هو الاختبار الحقيقي. |

القاعدة: كل ما يظهر لك اليوم هو عرض تجريبي (demo) ولا يصلح لإعطاء أسعار أو وعود لعملاء حقيقيين.

---

## 3) تشغيل كل شيء محلياً (docker compose)

المتطلبات: حاسوب (Windows/Mac/Linux) مع **Docker Desktop** (أو Docker Engine + Compose v2)، و**Git**، و**Python 3.12+** (لسكربت الفحص)، و`make` (على ويندوز استخدم WSL أو نفّذ الأوامر يدوياً كما أدناه).

خطوات:
1. نزّل المشروع: `git clone <رابط المستودع>` ثم ادخل المجلد `factory-finder`.
2. انسخ ملف الإعدادات: `cp .env.example .env`
3. ولّد أسراراً عشوائية (3 مرات، واحد لكل متغير) بالأمر:
   `python -c "import secrets;print(secrets.token_urlsafe(48))"`
   وضعها في `.env`: `FF_GATEWAY_JWT_SECRET` و`FF_INTERNAL_TOKEN` و`FF_GATEWAY_ADMIN_TOKEN`. (لا ترسلها لأحد ولا تضعها في GitHub؛ المستودع **عام**.)
4. شغّل: `docker compose up --build` (أول مرة تستغرق وقتاً). تظهر البوابة على `http://localhost:8000`. افحص: `http://localhost:8000/health` و`http://localhost:8000/ready`.
5. اختبار شامل آلي: `make venv` (مرة واحدة) ثم `make compose-e2e`. يبني ويشغّل كل شيء، ينفذ سيناريو كامل عبر البوابة، ثم يُطفئ ويمسح البيانات (`down -v`). النجاح = كل الخطوات OK (بعض خطوات الدفع/demand تظهر SKIP وهذا طبيعي إن لم تضبط `FF_E2E_ADMIN_TOKEN`).
6. للإيقاف: `docker compose down` (أو `docker compose down -v` لمسح البيانات).
7. اختبارات بدون Docker: `make venv` ثم `make test` و`make lint`.

لوحة الإدارة: ضع `FF_GATEWAY_SERVE_ADMIN=true` مع `FF_GATEWAY_ADMIN_TOKEN` ثم افتح `http://localhost:8000/admin/` وأدخل التوكن. **ملاحظة:** ملف `docker-compose.yml` يمرّر الآن للحاويات مفاتيح الإطفاء و`FF_ENV` و`FF_GATEWAY_SERVE_ADMIN` وإعدادات البريد والإشعارات والتتبع والشحن الحقيقي والمحوّلات وتوكنات الإدارة من `.env` (القيم الفارغة تعني السلوك الافتراضي). الإعدادات الدقيقة الأخرى (مثل حدود المعدل `FF_GATEWAY_*_RATE_LIMIT_PER_MINUTE` و`FF_GATEWAY_TRUSTED_PROXIES` و`FF_GATEWAY_REDIS_URL`) غير ممرَّرة بعد؛ أضف سطرها تحت `environment:` للخدمة المعنية. تحقق بالأمر: `docker compose config | grep NAME`. إدارة المنشورات والشحن والتوثيق (`/v1/admin/feed/*` و`/v1/admin/freight/*` و`/v1/admin/trust/verification/*`) تمر عبر البوابة وتحتاج `FF_GATEWAY_ADMIN_TOKEN` مع توكن الخدمة نفسها (`FF_FEED_ADMIN_TOKEN` و`FF_FREIGHT_ADMIN_TOKEN` و`FF_TRUST_ADMIN_TOKEN`) بالقيمة نفسها على البوابة وعلى الخدمة؛ إن نقص أحدهما فالمسار يعطي 404. وعرض الملفات الخاصة (وثائق التوثيق) يحتاج `FF_MEDIA_ADMIN_TOKEN` بالقيمة نفسها على البوابة وخدمة media.

قاعدة البيانات: افتراضياً SQLite داخل الحاوية وتضيع عند إعادة الإنشاء. للاستخدام الحقيقي استخدم PostgreSQL (الخطوات في `docs/DEPLOY.md` و`docs/DB.md`).

إن فشل شيء: `docker compose ps` ثم `docker compose logs --tail=200 <اسم الخدمة>`، وانظر `docs/RUNBOOK.md`.

---

## 4) بناء APK واختباره على هاتف أندرويد

التطبيق يُبنى تلقائياً في GitHub Actions (workflow اسمه `mobile`)، لا حاجة لتثبيت Flutter عندك.

1. ادخل مستودع GitHub، تبويب **Actions**، اختر **mobile**. يعمل تلقائياً عند أي تغيير في `apps/mobile`، أو اضغط **Run workflow** (workflow_dispatch).
2. افتح آخر تشغيل ناجح (علامة خضراء). في أسفل الصفحة قسم **Artifacts** حمّل `factory-finder-debug-apk` (ملف zip؛ يُحفظ 14 يوماً فقط). فك الضغط لتحصل على `app-debug.apk`.
3. انقل الملف للهاتف (كابل، Telegram، Drive).
4. على الهاتف: افتح الملف، اسمح بـ"التثبيت من مصادر غير معروفة" لتطبيق الملفات إن طُلب، ثم ثبّت.
5. افتح التطبيق. هذا الـAPK مبني بالوضع **الوهمي** (`FF_MOCK=true`): يعمل بدون أي خادم ببيانات تجريبية. استخدمه للتأكد أن الشاشات والعربية واتجاه RTL سليمة.
6. إن فشل البناء: افتح الخطوة الحمراء في Actions؛ رسائل الخطأ ملخصة في أعلى الصفحة (analyze/test/build).

اختبار مع الخادم الحقيقي (الوضع غير الوهمي): الـAPK الافتراضي من Actions وهمي. للاتصال بخادمك يلزم بناء جديد بالخيارين `--dart-define=FF_MOCK=false --dart-define=FF_API_BASE_URL=https://عنوان-الخادم` (من Actions: اضغط Run workflow واكتب `api_base_url` وغيّر `mock` إلى false). يمكن تغيير عنوان الخادم من شاشة الملف الشخصي، لكن فقط عندما يكون التطبيق مبنياً بـ`FF_MOCK=false`. الإصدارات النهائية على الأندرويد تتطلب HTTPS.

قائمة ما تفحصه على الهاتف: العربية والاتجاه، البحث، صفحة المنتج، حاسبة الكلفة (بغداد/إسطنبول/دبي/برلين)، إنشاء طلب وعرض، الدردشة، التتبع، تبديل اللغة، فتح وإغلاق التطبيق (حفظ الجلسة). سجّل أي خلل بلقطة شاشة وأرسله لـClaude.

---

## 5) كيف تفعّل البيانات الحقيقية (الحسابات والمفاتيح)

كل المحوّلات (adapters) **مطفأة افتراضياً** وغير مجرَّبة مع خدمات حقيقية؛ أول تفعيل لكل منها يحتاج اختباراً ومطابقة مع الوثائق الرسمية للمزود. القواعد: واجهات رسمية أو بيانات مرخّصة فقط، لا كشط للمواقع بخلاف شروطها، حد أدنى 3 ثوانٍ بين الطلبات لكل موقع.

| الحاجة | ما تحصل عليه | متغيرات البيئة |
|---|---|---|
| بيانات الموردين (المرحلة 4) | حساب مطوّر في Alibaba Open Platform (أو مزود بيانات مرخّص مثل مغذّي Made-in-China الشريكي؛ لا يوجد API عام له)؛ AliExpress وواجهة 1688 لهما حقول جاهزة. تحقق من الشروط التجارية ونطاق الاستخدام قبل الاشتراك. | `FF_SOURCING_ADAPTERS` (مثل `alibaba_openapi`)، `FF_SOURCING_ALIBABA_APP_KEY`، `FF_SOURCING_ALIBABA_APP_SECRET`، `FF_SOURCING_ALIBABA_ACCESS_TOKEN` |
| أسعار الشحن | مزود أسعار شحن (بحري/جوي) يقدم API ومفتاحاً بترخيص يسمح بعرض الأسعار في تطبيق. المطلوب مطابقة 3 مسارات مع عروض مخلّص/شركة شحن (±15%). | `FF_LOGISTICS_FREIGHT_PROVIDER=http`، `FF_LOGISTICS_FREIGHT_URL`، `FF_LOGISTICS_FREIGHT_API_KEY` |
| أسعار الصرف | مجاني بدون مفتاح | `FF_LOGISTICS_FX_PROVIDER=ecb` |
| تتبع الشحنات | مجمّع تتبع مرخّص للحاويات، وآخر لبوالص الشحن الجوي (AWB)، وآخر لمواقع السفن (AIS). | `FF_TRACKING_PROVIDER=http`، `FF_TRACKING_CONTAINER_BASE_URL`/`_API_KEY`، `FF_TRACKING_AWB_BASE_URL`/`_API_KEY`، `FF_TRACKING_VESSEL_BASE_URL`/`_API_KEY` |
| إشعارات Push (FCM) | مشروع Firebase وحساب خدمة (service account JSON). **يلزم أيضاً إضافة Firebase للتطبيق نفسه** (غير موجود اليوم) وملف `google-services.json`. | `FF_NOTIFY_PUSH=fcm`، `FF_NOTIFY_FCM_PROJECT_ID`، `FF_NOTIFY_FCM_CREDENTIALS_FILE` أو `FF_NOTIFY_FCM_CREDENTIALS_JSON` |
| بريد (SMTP) | خدمة بريد (SMTP) باسم نطاقك، مع SPF/DKIM. للتحقق من البريد والملخص اليومي. | للتحقق: `FF_GATEWAY_MAIL_BACKEND=smtp` + `FF_GATEWAY_SMTP_*`؛ للملخص: `FF_NOTIFY_EMAIL=smtp` + `FF_NOTIFY_SMTP_*` |
| الدفع بـUSDT على TRON | **محفظتك الخاصة** (عنوان عام فقط، لا تضع مفتاحاً خاصاً أبداً في النظام)، ومفتاح مزود explorer (TronGrid أو مماثل). | `FF_PAYMENTS_PROVIDER=usdt_tron`، `FF_PAYMENTS_USDT_RECEIVE_ADDRESS`، `FF_PAYMENTS_USDT_CONTRACT`، `FF_PAYMENTS_USDT_EXPLORER_URL`، `FF_PAYMENTS_USDT_EXPLORER_API_KEY`، `FF_PAYMENTS_WEBHOOK_SECRET_USDT_TRON` |
| بطاقات (لاحقاً) | بعد تأسيس شركة بريطانية وPayoneer/Stripe (المرحلة 6). غير مبنية بعد. | — |
| تخزين الصور على سحابة (اختياري) | حاوية S3 متوافقة (هيكل غير مجرَّب) | `FF_MEDIA_STORAGE_BACKEND=s3` + `FF_MEDIA_S3_*` |
| نموذج لغوي للمساعد (اختياري) | مفتاح API من Anthropic | `FF_ASSISTANT_LLM=anthropic`، `FF_ASSISTANT_LLM_API_KEY` |

---

## 6) ورقة غش المتغيرات حسب الخدمة

كل القيم تُكتب في `.env` أو بيئة الخادم، **القيم فارغة هنا عمداً. لا تضع أسراراً في المستودع أبداً.** تذكّر ملاحظة compose أعلاه (المتغيرات الشائعة ممرَّرة؛ غيرها يجب كتابته في `docker-compose.yml` ليصل للحاوية). كل خدمة تقرأ أيضاً `FF_INTERNAL_TOKEN` (الرمز المشترك بين البوابة والخدمات). منافذ الخدمات الداخلية: انظر `docs/API_OVERVIEW.md`.

عام: `FF_ENV=production` (الخدمات ترفض البدء بلا رموز)، `FF_LOG_FORMAT=text` (سجلات مقروءة محلياً).

- **gateway** (البادئة `FF_GATEWAY_`): `JWT_SECRET`، `ADMIN_TOKEN`، `DATABASE_URL`، `UPSTREAMS` (JSON)، `CORS_ORIGINS` (قائمة JSON، الافتراضي `[]`)، `TRUSTED_PROXIES`، `RATE_LIMIT_PER_MINUTE`، `AUTH_RATE_LIMIT_PER_MINUTE`، `USER_WRITE_RATE_LIMIT_PER_MINUTE`، `MEDIA_RATE_LIMIT_PER_MINUTE`، `REDIS_URL`، `SERVE_ADMIN`، `ADMIN_DIR`، `MAIL_BACKEND` (off/mock/smtp)، `REQUIRE_EMAIL_VERIFIED`، `MAIL_FROM`، `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`، `VERIFY_URL_TEMPLATE`، `ACCESS_TTL_SECONDS`، `REFRESH_TTL_SECONDS`، `MAX_BODY_BYTES`، `DELETION_GRACE_DAYS`، `PRIVACY_RATE_LIMIT_PER_MINUTE`. كما يقرأ بلا بادئة: `FF_INTERNAL_TOKEN`، `FF_SOURCING_ADMIN_TOKEN` (إدارة الإبلاغات)، `FF_PAYMENTS_ADMIN_TOKEN` (إدارة صندوق أحداث الدفع)، `FF_TRUST_ADMIN_TOKEN` و`FF_FREIGHT_ADMIN_TOKEN` و`FF_FEED_ADMIN_TOKEN` و`FF_MEDIA_ADMIN_TOKEN`. في `FF_ENV=production` ترفض البوابة البدء بلا `FF_GATEWAY_JWT_SECRET` و`FF_GATEWAY_ADMIN_TOKEN`.
- **sourcing** (`FF_SOURCING_`): `ENABLED_SOURCES` (الافتراضي `mock,native`)، `ADAPTERS`، `LICENSED_MAPPINGS`، `DATABASE_URL`، `DB_AUTO_CREATE`، `TRUST_MODE`، `TRUST_BASE_URL`، `ADMIN_TOKEN`، `ALIBABA_APP_KEY`، `ALIBABA_APP_SECRET`، `ALIBABA_ACCESS_TOKEN`، `ALIBABA_OPENAPI_DISABLED`، `KILL_SWITCH`، `ALIEXPRESS_APP_KEY`/`_APP_SECRET`/`_TRACKING_ID`، `MIC_API_BASE`/`MIC_API_KEY`/`MIC_ALLOW_PUBLIC_PAGES`، `S1688_APP_KEY`/`S1688_APP_SECRET`، `MIN_REQUEST_INTERVAL_S`، وحدود وإبقاء البيانات: `MAX_LISTINGS_PER_SUPPLIER` (200)، `CREATE_RATE_PER_HOUR` (30)، `PRICE_HISTORY_RETENTION_DAYS` (400)، `ANALYTICS_RETENTION_DAYS` (400).
- **logistics** (`FF_LOGISTICS_`): `GEO_URL`، `FX_PROVIDER` (mock/ecb)، `FREIGHT_PROVIDER` (mock/http)، `FREIGHT_URL`، `FREIGHT_API_KEY`، `FREIGHT_DISABLED`، `KILL_SWITCH`، `FREIGHT_MIN_INTERVAL_S`.
- **geo** (`FF_GEO_`): لا إعدادات إلزامية.
- **trust** (`FF_TRUST_`): `ADAPTER` (mock افتراضياً)، `DATABASE_URL`، `ADMIN_TOKEN`، `VERIFICATION_HASH_KEY` (إلزامي مع `FF_ENV=production`؛ لا تغيّره بعد الإطلاق)، `REVIEWS_SOURCE` (off/mock/http)، `REVIEWS_BASE_URL`، `REPORT_RETENTION_DAYS` (365)، `SNAPSHOT_RETENTION_DAYS` (730)؛ الأوزان والعتبات قابلة للضبط (`docs/decisions/trust-v2.md`).
- **rfq** (`FF_RFQ_`): `DATABASE_URL`، `DB_AUTO_CREATE`، `SOURCING_URL`، العمولات `COMMISSION_PRODUCT` (0.03) و`COMMISSION_RAW_MATERIAL` (0.02) و`COMMISSION_PRODUCTION_LINE` (0.04)، `MIN_COMMISSION_USD` (25)، `REQUIRE_BOTH_INVOICES`.
- **messaging** (`FF_MESSAGING_`): `DATABASE_URL`، `DB_AUTO_CREATE`، `ABUSE_FILTER_ENABLED`، `ABUSE_ACTION` (flag/mask)، `ABUSE_TERMS_EXTRA`، `ATTACHMENT_MAX_BYTES`، `SEND_RATE_LIMIT`.
- **tracking** (`FF_TRACKING_`): `DATABASE_URL`، `DB_AUTO_CREATE`، `PROVIDER` (mock/http)، `CONTAINER_BASE_URL`/`CONTAINER_API_KEY`، `AWB_BASE_URL`/`AWB_API_KEY`، `VESSEL_BASE_URL`/`VESSEL_API_KEY`، `HTTP_MIN_INTERVAL_SECONDS`، `FALLBACK_TO_MOCK`، `KILL_SWITCH`، `CONTAINER_DISABLED`/`AWB_DISABLED`/`VESSEL_DISABLED`، `REFRESH_JOB_ENABLED`، `REFRESH_JOB_INTERVAL_HOURS`، `NOTIFY_RELAY` (off/on)، `NOTIFY_BASE_URL`.
- **notifications** (`FF_NOTIFICATIONS_` للأساسيات): `DATABASE_URL`، `DB_AUTO_CREATE`، `SOURCING_BASE_URL`، `SCHEDULER_ENABLED` (يشغّل التقييم الدوري وحذف التنبيهات الأقدم من `ALERT_RETENTION_DAYS`=180 والتسليمات الأقدم من `DELIVERY_RETENTION_DAYS`=30)؛ وللتسليم (بادئة `FF_NOTIFY_`): `PUSH` (off/mock/fcm)، `FCM_PROJECT_ID`، `FCM_CREDENTIALS_FILE`، `FCM_CREDENTIALS_JSON`، `EMAIL` (off/mock/smtp)، `SMTP_HOST`، `SMTP_PORT`، `SMTP_USER`، `SMTP_PASSWORD`، `SMTP_FROM`.
- **assistant** (`FF_ASSISTANT_`): `LLM` (off/mock/anthropic)، `LLM_API_KEY`، `LLM_MODEL`، `LLM_BASE_URL`، `LLM_REWRITE`، `QUOTA_PER_DAY`، `ANON_QUOTA_PER_DAY`، وعناوين الخدمات `SOURCING_URL` وغيرها.
- **demand** (`FF_DEMAND_`): `ENABLED` (false)، `DAILY_CAP` (20)، `DATABASE_URL`، `DB_AUTO_CREATE`، `SOURCING_BASE_URL`، `USE_MOCK_SOURCING`، `SIGNAL_RETENTION_DAYS` (90)، `REJECTED_DRAFT_RETENTION_DAYS` (90).
- **payments** (`FF_PAYMENTS_`): `PROVIDER` (mock/usdt_tron/off)، `DATABASE_URL`، `DB_AUTO_CREATE`، `ADMIN_TOKEN`، `WEBHOOK_SECRET_MOCK`، `WEBHOOK_SECRET_USDT_TRON`، `USDT_RECEIVE_ADDRESS`، `USDT_CONTRACT`، `USDT_EXPLORER_URL`، `USDT_EXPLORER_API_KEY`، `RFQ_URL`، `COMMISSION_*` و`MIN_COMMISSION_USD` (كما في rfq؛ يجب أن تتطابق)، وإبقاء البيانات (يعمل داخل `POST /v1/payments/sweep`، والقيمة 0 تعطّله): `WEBHOOK_EVENT_RETENTION_DAYS` (180)، `OUTBOX_DELIVERED_RETENTION_DAYS` (180)، `ATTEMPT_RETENTION_DAYS` (365)؛ ولا تُحذف الفواتير ولا دفتر الأستاذ أبداً. حدود: `MAX_OPEN_INVOICES_PER_USER` (20)، `MAX_INVOICES_PER_USER_PER_DAY` (50).
- **media** (`FF_MEDIA_`): `DATABASE_URL`، `STORAGE_BACKEND` (local/s3)، `STORAGE_ROOT`، `PUBLIC_BASE_URL` (عنوان البوابة العام)، `MAX_UPLOAD_BYTES`، `S3_BUCKET`، `S3_REGION`، `S3_ENDPOINT_URL`، `S3_ACCESS_KEY_ID`، `S3_SECRET_ACCESS_KEY`، `SIGNING_KEY` (إلزامي مع `FF_ENV=production`؛ لروابط الملفات الخاصة)، `ADMIN_TOKEN`، `MAX_FILES_PER_USER` (200)، `MAX_UPLOADS_PER_HOUR` (30).
- **feed** (`FF_FEED_`، المنفذ 8113): `DATABASE_URL`، `DB_AUTO_CREATE`، `ADMIN_TOKEN`، `MEDIA_BASE_URL`، `REPORT_HIDE_THRESHOLD` (3 مبلّغين مختلفين)، وحدود: `MAX_POSTS_PER_SUPPLIER` (500)، `MAX_FOLLOWS_PER_USER` (500)، `MAX_COMMENTS_PER_POST` (1000)، و`RATE_POSTS`/`RATE_COMMENTS`/`RATE_LIKES`/`RATE_FOLLOWS`/`RATE_REPORTS` في الساعة (القيمة 0 تعطّل الحد).
- **freight** (`FF_FREIGHT_`، المنفذ 8114): `DATABASE_URL`، `DB_AUTO_CREATE`، `ADMIN_TOKEN`، `REPORT_HIDE_THRESHOLD` (3)، حدود: `MAX_OPEN_REQUESTS_PER_BUYER` (50)، `MAX_QUOTES_PER_REQUEST` (50)، `MAX_LANES_PER_FORWARDER` (50)، `MAX_APPLICATIONS_PER_USER` (5)، وأوزان الترتيب `WEIGHT_PRICE`/`WEIGHT_TRANSIT`/`WEIGHT_RATING` (50/30/20).
- **قواعد البيانات**: لكل خدمة `FF_<SVC>_DATABASE_URL` مستقل، و`FF_POSTGRES_PASSWORD` و`FF_DOCKER_EXTRAS=pg` للتشغيل مع PostgreSQL.
- **التطبيق** (وقت البناء `--dart-define`): `FF_MOCK` و`FF_API_BASE_URL`.

قائمة مفاتيح الإطفاء الكاملة بالأسماء الدقيقة: `docs/RUNBOOK.md` القسم 5.

---

## 7) فئات تكاليف الاستضافة (بدون أسعار؛ ماذا تفحص)

لم نضع أرقاماً لأن الأسعار تتغير. افحص عروض مزودين متعددين لكل بند:
1. **خادم/VPS** يشغّل 15 حاوية: الذاكرة والمعالج المطلوبان، قارن مزودي VPS أو سحابة. ابدأ صغيراً وراقب `docker stats`.
2. **PostgreSQL مُدار أو ذاتي** + **نسخ احتياطي خارج الخادم** (تخزين كائنات).
3. **تخزين الصور** (قرص الخادم أو S3 مع تكلفة نقل البيانات).
4. **النطاق (Domain)** وشهادة **TLS** (Let's Encrypt مجانية عادة) و**Reverse proxy** (Caddy/nginx).
5. **البريد المرسَل (SMTP)** ورسوم الإرسال حسب الحجم.
6. **Firebase/FCM** (الإشعارات غالباً بلا رسوم لكن راجع الحصص).
7. **بيانات الموردين وأسعار الشحن والتتبع**: غالباً أكبر بند متكرر؛ اطلب عرض أسعار وشروط ترخيص (هل يسمح بعرض البيانات للمستخدمين وتخزينها مؤقتاً؟).
8. **نموذج المساعد** (إن فعّلته): رسوم لكل استدعاء؛ الحدود اليومية مضبوطة بـ`FF_ASSISTANT_QUOTA_PER_DAY`.
9. **حسابات المتاجر**: Google Play (رسم تسجيل لمرة واحدة) وApple Developer (اشتراك سنوي): تحقق من القيمة الحالية.
10. **الشركة البريطانية، Payoneer، محامٍ، محاسب**: رسوم تأسيس وخدمات سنوية؛ تحقق.
11. **مراقبة (uptime/logs)** إن لم تكن مجانية.

أول حد للأخطاء في الميزانية: لا تشترك بأي API مدفوع قبل أن تعرف كم طلباً يوميا ستحتاج (الذاكرة المؤقتة cache موجودة: ساعة للتتبع، 6 ساعات للصرف والشحن).

---

## 8) قائمة التدقيق القانوني (راجع محامياً)

- **شروط مصادر البيانات**: اقرأ شروط كل مزود (علي بابا، 1688، AliExpress، Made-in-China): هل يسمح بعرض بياناتهم وصورهم داخل تطبيق تجاري؟ هل يمنع التخزين؟ هل يلزم الإشارة للمصدر؟ ممنوع تجاوز CAPTCHA أو تسجيل الدخول أو الكشط المخالف لـ robots.txt.
- **سياسة الخصوصية وشروط الاستخدام** بالعربية والإنكليزية، تغطي: البيانات المجمَّعة (بريد، هاتف، شركة، محادثات، صور، موقع)، مدة الاحتفاظ، حق الحذف، مشاركة البيانات مع المزودين. مطلوبة لمتجري Google وApple. تحقق من قانون حماية البيانات في العراق وفي دول المستخدمين (مثل GDPR إن كان لك مستخدمون في أوروبا).
- **العمولة والدفع**: هل استلام أموال المشتري ثم تحويلها للمورد، أو أخذ عمولة وساطة، يتطلب ترخيصاً (وساطة تجارية، خدمات دفع، وحدات عملات رقمية) في العراق وفي بلد الشركة (بريطانيا)؟ هل USDT مسموح استخدامه وتحصيله في العراق؟ تحقق من الضرائب ومكافحة غسل الأموال (KYC) قبل استلام أول دولار.
- **أن المنصة وسيط**: صياغة واضحة للمسؤولية عن جودة البضاعة والنزاعات والاسترجاع.
- **إخلاء مسؤولية الجمارك والشحن**: يجب أن يظهر في التطبيق أن الكلفة تقديرية، وأن الرسوم والرموز الجمركية (HS) للإرشاد فقط وتحقق منها مع مخلّص جمركي، وأن التطبيق ليس استشارة جمركية أو قانونية.
- **قوائم العقوبات والتصدير**: التأكد من عدم تسهيل تجارة مع جهات أو بضائع خاضعة لحظر.
- **المحتوى والإبلاغ**: سياسة الإعلانات الممنوعة وآلية الإبلاغ والإزالة (موجودة تقنياً: إبلاغ + إخفاء).
- **فيسبوك/السوشيال (المرحلة 5)**: اقرأ شروط المنصة. لا رسائل خاصة آلية للغرباء؛ ردود علنية فقط، بحجم قليل، وبموافقة بشرية.
- **الشركة**: تأسيس الشركة البريطانية (يستغرق أسابيع) قبل الدفع بالبطاقات.
- **الملكية الفكرية**: اسم "مُوَرِّد" والشعار، وعدم استخدام علامات الآخرين.

---

## 9) قائمة النشر على المتاجر

**Google Play (أندرويد)**
1. حساب Play Console (رسوم تسجيل؛ تحقق) والتحقق من الهوية.
2. اسم الحزمة النهائي (حالياً `com.factoryfinder` عند توليد المشروع في CI، قرره قبل النشر لأنه لا يتغير بعدها).
3. بناء **release** موقّع (App Bundle `.aab`) مع مفتاح توقيع تحتفظ به بنسخ احتياطية آمنة خارج المستودع. الـCI الحالي يبني debug فقط.
4. الاتصال بخادم عبر **HTTPS** فقط، وتعطيل وضع mock (`FF_MOCK=false`).
5. صفحة المتجر: وصف عربي/إنكليزي، لقطات شاشة، أيقونة، رابط سياسة الخصوصية، نموذج Data safety، تصنيف المحتوى، حساب تجريبي لفريق المراجعة.
6. إن أضفت Firebase: ملف `google-services.json`.
7. اختبار مغلق (Internal/Closed testing) ثم إنتاج؛ تحقق من متطلبات الحسابات الجديدة (عدد المختبرين ومدة الاختبار) في سياسات Google الحالية.

**Apple (iOS)**
1. حساب Apple Developer (اشتراك سنوي؛ تحقق) وجهاز Mac للبناء (أو خدمة بناء سحابية بـmacOS). لم نبنِ iOS أبداً.
2. Bundle ID، شهادات التوقيع، TestFlight للتجربة قبل App Store.
3. مفاتيح `Info.plist` المطلوبة بحسب المكتبات المستخدمة (`image_picker` لرفع الصور):
   - `NSPhotoLibraryUsageDescription`: سبب الوصول لمكتبة الصور.
   - `NSCameraUsageDescription`: سبب استخدام الكاميرا.
   - `NSMicrophoneUsageDescription`: فقط إن سُجّل فيديو.
   - نصوص الأسباب بالعربية والإنكليزية. وأي مفاتيح لمكتبات تضاف لاحقاً (مثل الإشعارات: قدرة Push Notifications و Background Modes، وتفعيل APNs داخل Firebase).
   - لا تكتب `NSAllowsArbitraryLoads`: استخدم HTTPS (ATS).
4. App Privacy (nutrition labels)، رابط الخصوصية، حذف الحساب داخل التطبيق (Apple وGoogle تشترطانه لتطبيقات تنشئ حسابات؛ **واجهة الحذف والتصدير جاهزة في الخادم** (`DELETE /v1/me` و`GET /v1/me/export`، التفاصيل في `docs/decisions/account-deletion.md`) **لكن لا توجد شاشة لها في التطبيق اليوم**، أضفها قبل النشر. ويجب أن تذكر سياسة الخصوصية الاستثناءات: سجلات الدفع والصفقات وتدقيق التوثيق تبقى للمراجعة المالية والقانونية).
5. ملاحظات المراجعة: حساب تجريبي، وشرح أن الدفع بعملة رقمية للسلع المادية (تحقق من سياسة Apple للدفع الخارجي).
6. بنود المحتوى المنشأ من المستخدمين: الإبلاغ والحجب (موجود جزئياً: إبلاغ عن الإعلانات وفلتر في الدردشة) — تحقق من اكتمال المتطلبات.

---

## 10) قائمة الإطلاق وبوابات "اذهب / لا تذهب" (مرتبطة بالـROADMAP)

القاعدة: لا تنتقل لمرحلة قبل نجاح بوابتها. "اختبار" = `make test` و`make lint` و`make compose-e2e` والـCI أخضر.

| المرحلة | بوابة Go | علامات No-Go |
|---|---|---|
| **0 الأساس** | `make test` أخضر؛ CI أخضر؛ كل خدمة ترد على `/health` | أي اختبار أحمر |
| **1 النواة (الصين إلى أي دولة)** | بحث ثم إعلان ثم كلفة كاملة إلى بغداد/إسطنبول/دبي/برلين بخيارات معقولة ومشروحة؛ التطبيق يعمل بالوضع الوهمي | أرقام غير منطقية؛ شاشة تنهار |
| **2 السوق (طلبات/عروض/صفقات/دردشة)** | مشتري ينشر طلباً، مورد يعرض، المشتري يقبل، تُسجَّل الصفقة والعمولة؛ الدردشة تعمل | عمولة خاطئة؛ رسائل لا تصل |
| **3 الاحتفاظ (تتبع، تنبيهات، مساعد)** | تتبع حاوية من البداية للنهاية (وهمي)؛ تنبيه انخفاض سعر يعمل؛ المساعد يجيب على طلب "خط إنتاج معجنات مستعمل من الصين يصل بغداد" | — (هذه المراحل 0-3 مكتملة على البيانات الوهمية حسب STATUS) |
| **4 بيانات حقيقية** | نتائج حقيقية لفئة واحدة من مصدر رسمي/مرخّص؛ عروض الشحن ضمن ±15% من عرض مخلّص حقيقي على 3 مسارات؛ التطبيق جُرّب على هاتف حقيقي؛ اختبار docker compose ناجح على خادم حقيقي مع PostgreSQL ونسخ احتياطي مُجرَّب الاسترجاع؛ **ملاحظات الأمان في `docs/fixes/` معالجة** | ترخيص بيانات غير واضح؛ أي سر في المستودع؛ التطبيق لم يُجرَّب على جهاز |
| **5 مطابقة الطلب** | موافقة بشرية على كل رد؛ 20 رداً مطابقاً/يوم دون إنذارات حساب؛ تتبع التحويل؛ مراجعة شروط المنصة | رسائل خاصة آلية؛ إنذار من المنصة؛ `FF_DEMAND_ENABLED` مفتوح بلا مراجِع |
| **6 الدفع والإطلاق** | أول عمولة محصَّلة فعلاً؛ التطبيق على Play وTestFlight/App Store؛ مراجعة قانونية للدفع والعمولة منتهية؛ شركة بريطانية وPayoneer قبل البطاقات | لا ترخيص/رأي قانوني؛ webhook الدفع بلا سر؛ عدم اختبار الاسترجاع |

قائمة ما قبل الإطلاق العام (كلها مطلوبة):
- [ ] أسرار قوية: `FF_GATEWAY_JWT_SECRET`، `FF_INTERNAL_TOKEN`، `FF_GATEWAY_ADMIN_TOKEN` (والرموز الأخرى)، و`FF_ENV=production`.
- [ ] HTTPS عبر reverse proxy؛ البوابة فقط مكشوفة؛ لا منافذ خلفية مفتوحة؛ `FF_GATEWAY_TRUSTED_PROXIES` مضبوط.
- [ ] PostgreSQL + نسخ احتياطي مجدول خارج الخادم + استرجاع مُجرَّب (`docs/RUNBOOK.md` القسم 3).
- [ ] مدخل webhook الدفع المعزول إن فُعّل الدفع الحقيقي (`docs/DEPLOY.md`).
- [ ] مفاتيح الإطفاء مجرَّبة (RUNBOOK القسم 5) وتعرف من يستخدمها.
- [ ] سياسة الخصوصية وشروط الاستخدام وإخلاء المسؤولية في التطبيق.
- [ ] شاشة حذف الحساب وتصدير البيانات في التطبيق (مطلوبة للمتاجر؛ **الواجهة الخلفية جاهزة**: `DELETE /v1/me` يطلب كلمة المرور، و`GET /v1/me/export`) وواجهة موافقة مطالبات الموردين (متوفرة في لوحة الإدارة).
- [ ] ملاحظات خصوصية للمالك: (1) الحذف يعمل فوراً افتراضياً؛ إن أردت مهلة تراجع اضبط `FF_GATEWAY_DELETION_GRACE_DAYS` (الدخول بكلمة المرور خلالها يلغي الحذف). (2) المحذوف يُمسح أو يُجهَّل في كل الخدمات لكن تبقى سجلات الدفع (دفتر الأستاذ والفواتير) والصفقات وتدقيق توثيق الموردين بمعرّف مجهول لأغراض مالية وقانونية؛ اذكر هذا وفترة بقاء النسخ الاحتياطية في سياسة الخصوصية. (3) راقب `GET /v1/admin/account-deletions?status=dead` أسبوعياً: أي خدمة فشل حذفها تحتاج تدخلاً. (4) جميع الخدمات يجب أن تشارك `FF_INTERNAL_TOKEN` نفسه مع البوابة وإلا لن يكتمل الحذف.
- [ ] Rate limit عبر Redis إن شغّلت أكثر من نسخة من البوابة.
- [ ] اختبار على هاتفين حقيقيين على الأقل وشبكة ضعيفة.
- [ ] خطة دعم: من يرد على المستخدمين وعلى النزاعات؟

الثغرات المعروفة (من STATUS): تحديد المعدل في ذاكرة العملية فقط؛ جداول الرسوم والشحن تقريبية؛ بعض الإحداثيات غير مؤكدة؛ المنافذ المباشرة للخدمات تثق بترويسة `X-User-Id` إن لم يُضبط `FF_INTERNAL_TOKEN` (شبكة خاصة فقط).

---

## 11) ماذا تفعل أنت الآن (ملخص بالترتيب)

1. شغّل `make compose-e2e` على جهازك وأخبر Claude بالنتيجة (أول تشغيل حقيقي).
2. حمّل الـAPK من Actions وجرّبه على هاتفك وأرسل ملاحظاتك.
3. قرر مصدر البيانات الأول (Alibaba Open Platform أو مزود مرخّص) وقدّم على الحساب.
4. ابدأ أوراق الشركة البريطانية وراجع محامياً في نقاط القسم 8.
5. جهّز محفظة USDT (TRON) خاصة بك لاستقبال العمولات (العنوان العام فقط).
