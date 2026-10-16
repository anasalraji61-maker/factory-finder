# دليل المالك: تحويل المحوّلات الوهمية (Mock Adapters) إلى حقيقية بشكل قانوني

> الغرض: لكل محوّل (adapter) في المشروع — ما هو المزوّد، أي برنامج/واجهة رسمية تتقدم لها، ما المطلوب منك، المتغيرات (env vars) الدقيقة، مفتاح الإيقاف (kill switch)، والتحذيرات القانونية.
> لا توجد قيم أسرار هنا. القيم تُوضع فقط في بيئة التشغيل (`.env` على الخادم) ولا تُرفع إلى المستودع (المستودع عام — CLAUDE.md القاعدة 5).

## 0. كيف تقرأ هذا الدليل (مهم: ما الذي تحقّقتُ منه)

أثناء كتابة الدليل كانت صفحات المزوّدين الرسمية (open.alibaba.com، developers.aliexpress.com، open.1688.com، DCSA، Firebase، Anthropic، وثائق TronGrid الخاصة بالمفتاح) **غير قابلة للجلب** من بيئة الوكيل (طلب الإذن لم يُجَب). لذلك:

- **[موثّق]** = قرأتُ الصفحة الرسمية فعلاً في هذه الجلسة.
- **[من الكود]** = مأخوذ من ملفات المستودع (`config.py` والمحوّلات) وهو دقيق بالنسبة للمستودع.
- **[غير مُتحقَّق]** = معرفة عامة أو نتيجة بحث لم تُقرأ صفحتها الرسمية. **تحقّق من الموقع الرسمي قبل التقديم أو الدفع.** لم أذكر أي سعر غير موثّق.

المصادر التي قُرئت فعلاً:
- حدود TronGrid: https://developers.tron.network/reference/rate-limits
- Frankfurter (أسعار الصرف): https://frankfurter.dev

روابط ظهرت في نتائج البحث ولم تُقرأ (نقطة بداية فقط، **غير مُتحقَّق**): https://dcsa.org/standards/track-and-trace ، https://developer.dcsa.org/explore-apis/track-and-trace ، https://developers.tron.network/reference-link/api-key ، https://open.alibaba.com ، https://developers.aliexpress.com ، https://open.1688.com ، https://firebase.google.com/docs/cloud-messaging ، https://docs.anthropic.com .

### قاعدة عامة لكل المحوّلات الحقيقية (من CLAUDE.md القاعدة 6 ومن الكود)
1. واجهات رسمية أو بيانات مرخّصة فقط. **ممنوع** كشط (scraping) المواقع بما يخالف شروط الاستخدام (ToS)، وممنوع تجاوز CAPTCHA أو تسجيل الدخول أو الجدار المدفوع.
2. احترام `robots.txt` (الكود يفرضه عبر `RobotsGuard` عند قراءة صفحات عامة).
3. حدّ الطلبات الافتراضي: طلب واحد كل 3 ثوانٍ لكل مضيف كحد أدنى (`FF_SOURCING_MIN_REQUEST_INTERVAL_S` و`FF_TRACKING_HTTP_MIN_INTERVAL_SECONDS` و`FF_LOGISTICS_FREIGHT_MIN_INTERVAL_S`)، مع تخزين مؤقت (cache) وUser-Agent صادق.
4. **كل محوّل حقيقي في المستودع هيكل غير مُتحقَّق من واجهة حقيقية** (الكود نفسه يقول UNVERIFIED). بعد حصولك على المفاتيح: سجّل استجابة حقيقية واستبدل بها ملفات fixtures الاصطناعية، ثم عدّل الـ mapping — هذا عمل للمطوّرين، لا تُفعّل في الإنتاج قبله.
5. التفعيل دائماً تدريجي: فعّل محوّلاً واحداً، راقب، وعند أي مشكلة اضغط مفتاح الإيقاف. الفشل يعود تلقائياً إلى الـ mock مع `warning`.

---

## 1. ترتيب الأولويات المقترح للمالك (عراقي، شركة بريطانية قيد التأسيس، Payoneer)

| # | المحوّل | لماذا بهذا الترتيب | يحتاج شركة؟ | الكلفة |
|---|---|---|---|---|
| 1 | أسعار الصرف FX (Frankfurter/ECB) | جاهز اليوم، بلا مفتاح، بلا تسجيل. يرفع دقة الكلفة الكاملة فوراً | لا | مجاني [موثّق] |
| 2 | إشعارات FCM (Firebase) | حساب Google مجاني؛ ضروري لتجربة التطبيق | لا | FCM مجاني [غير مُتحقَّق — راجع صفحة التسعير] |
| 3 | الدفع USDT على TRON (TronGrid) | بلا شركة ولا بنك؛ محفظتك أنت. مناسب لعراقي مقيّد بالبنوك | لا (لكن راجع الامتثال، القسم 7) | مفتاح TronGrid له طبقة مجانية [موثّق جزئياً] |
| 4 | LLM للمساعد (Anthropic) | اختياري ومطفأ افتراضياً؛ دفع بالبطاقة/Payoneer عبر شركة UK لاحقاً | يُفضَّل | بالاستهلاك [غير مُتحقَّق] |
| 5 | AliExpress Affiliate (البحث الأوّل عن منتجات حقيقية) | أسهل برنامج مصادر رسمي للتقديم عادةً (برنامج شركاء) | لا غالباً | مجاني غالباً [غير مُتحقَّق] |
| 6 | Alibaba.com Open Platform | أهم مصدر B2B لكن التسجيل كمطوّر/موافقة الصلاحيات قد تتطلب شركة وتحقّقاً | نعم غالباً | غير مُتحقَّق |
| 7 | تتبّع الحاويات/الشحن (DCSA عبر الناقلين، أو مجمّع مرخّص) | يتطلب عقوداً/مفاتيح مع ناقلين أو مجمّع مدفوع | نعم غالباً | غير مُتحقَّق |
| 8 | أسعار الشحن (Freightos-style) | غالباً اتفاقية تجارية مدفوعة | نعم | غير مُتحقَّق |
| 9 | Made-in-China (تغذية مرخّصة) | لا API عام معروف؛ يتطلب شراكة/ترخيص | نعم | غير مُتحقَّق |
| 10 | 1688 Open Platform | سوق محلي صيني؛ غالباً يتطلب كياناً صينياً | غالباً كيان صيني | غير مُتحقَّق |
| 11 | بيانات الثقة (Trust adapters) | مجرد هياكل معطّلة؛ لا شيء للتقديم الآن | — | — |

نصيحة: ابدأ بـ 1–3 هذا الأسبوع (بلا شركة)، ثم أطلق التقديمات الطويلة (5، 6، 7) بالتوازي لأنها تستغرق أسابيع، وأكمل الشركة البريطانية لأنها تفتح 4 و6 و7 و8.

---

## 2. أسعار الصرف (FX) — الأولوية 1

- **المحوّل:** `EcbFx` في `services/logistics/src/ff_logistics/adapters/fx.py`
- **المزوّد:** Frankfurter (مفتوح المصدر؛ يعتمد في الأصل على أسعار البنك المركزي الأوروبي ECB). [موثّق: https://frankfurter.dev]
- **التقديم/الموافقة:** لا شيء. بلا مفتاح ولا تسجيل. [موثّق]
- **الكلفة:** مجاني، بلا حصص (quotas) لكن يوجد تحديد معدّل ضد الإساءة. [موثّق]
- **ملاحظات قانونية:** الأسعار المدمجة (blended) مجانية للاستخدام التجاري، والاستعلام المباشر عن مزوّد معيّن يخضع لشروطه، ويُسمح بتخزين الأسعار اليومية مؤقتاً. [موثّق] — الكود يخزّن 6 ساعات افتراضياً (مناسب).
- **تنبيه تقني (للمطوّر):** الكود يستدعي `https://api.frankfurter.dev/v1/latest`؛ الموقع حالياً يوثّق نقاط `/v2/...`. تأكد أن `/v1` ما زالت تعمل أو حدّث `FF_LOGISTICS_FX_URL`. [غير مُتحقَّق]. الدينار العراقي (IQD) وبعض العملات تُملأ من جدول mock ثابت عند غيابها (حسب الكود) — الأسعار الرسمية للدينار تحتاج مصدراً آخر لاحقاً؛ لا تعتبرها حيّة. المخرجات تحمل `source` (مثل `ecb` أو `mock-fallback` أو `ecb-stale`) فتأكد أن الواجهة تعرضه.
- **متغيرات البيئة [من الكود]:**
  - `FF_LOGISTICS_FX_PROVIDER=ecb` (القيمة الافتراضية `mock`)
  - اختياري: `FF_LOGISTICS_FX_URL` ، `FF_LOGISTICS_FX_CACHE_TTL_SECONDS`
- **مفتاح الإيقاف:** أعد `FF_LOGISTICS_FX_PROVIDER=mock`. (لا يوجد kill switch منفصل؛ الفشل يعود تلقائياً للـ mock.)

---

## 3. إشعارات الدفع (Push) عبر Firebase Cloud Messaging — الأولوية 2

- **المحوّل:** `FcmPush` في `services/notifications/src/ff_notifications/adapters/push.py` (واجهة HTTP v1: `fcm.googleapis.com/v1/projects/{project}/messages:send`، مصادقة بحساب خدمة service account) [من الكود]
- **المزوّد/البرنامج:** Firebase (Google). الخطوات: أنشئ مشروع Firebase ← فعّل Cloud Messaging ← أنشئ Service Account وحمّل ملف JSON ← اربط التطبيق (Android: `google-services.json`؛ iOS: مفتاح APNs من حساب Apple Developer).
- **ما المطلوب:** حساب Google عادي. iOS يتطلب عضوية Apple Developer (مدفوعة — تحقّق من السعر الحالي) [غير مُتحقَّق].
- **الكلفة:** FCM نفسه معروف بأنه بلا رسوم لكن تحقّق من صفحة Firebase الرسمية [غير مُتحقَّق].
- **تحذير:** ملف حساب الخدمة سرّ كامل — لا يوضع في المستودع أبداً. التقيّد بسياسات المتجرين (موافقة المستخدم على الإشعارات).
- **متغيرات البيئة [من الكود]:**
  - `FF_NOTIFY_PUSH=fcm` (القيم: `off` | `mock` | `fcm`؛ الافتراضي `off`)
  - `FF_NOTIFY_FCM_PROJECT_ID`
  - واحد فقط من: `FF_NOTIFY_FCM_CREDENTIALS_FILE` (مسار ملف على الخادم) أو `FF_NOTIFY_FCM_CREDENTIALS_JSON`
- **مفتاح الإيقاف:** `FF_NOTIFY_PUSH=off`.
- **بريد الملخص اليومي (Email)** في نفس الخدمة: `FF_NOTIFY_EMAIL=smtp` مع `FF_NOTIFY_SMTP_HOST` و`_PORT` و`_USER` و`_PASSWORD` و`_FROM`؛ إيقاف: `FF_NOTIFY_EMAIL=off`. استخدم مزوّد SMTP نظامياً (له سياسة مكافحة الرسائل المزعجة) واعتمد SPF/DKIM لنطاقك. وللبوابة (gateway) إعدادات منفصلة: `FF_GATEWAY_MAIL_BACKEND=smtp` و`FF_GATEWAY_SMTP_*` و`FF_GATEWAY_MAIL_FROM` و`FF_GATEWAY_VERIFY_URL_TEMPLATE`.

---

## 4. الدفع بـ USDT على شبكة TRON (TRC-20) — الأولوية 3

- **المحوّل:** `usdt_tron` في `services/payments/src/ff_payments/providers/usdt_tron.py`
- **المزوّد:** TronGrid (واجهة TRON الرسمية للعقد/الأحداث) أو أي مستكشف متوافق بالواجهة نفسها؛ الكود يرسل الترويسة `TRON-PRO-API-KEY` [من الكود].
- **ما المطلوب:** (أ) محفظتك الشخصية لاستلام USDT — **عنوان عام فقط (public address)**، لا مفتاح خاص أبداً في أي مكان. (ب) مفتاح API من لوحة TronGrid.
- **الحدود/الكلفة:** بدون مفتاح يتوقع تحديداً صارماً أو رفضاً؛ الحصص تعتمد على الخطة وتتغيّر، والمصدر الحاسم هو لوحة TronGrid؛ زيادة الحصة تتطلب طلباً (Contact Us) وليست تلقائية. [موثّق: https://developers.tron.network/reference/rate-limits] — لا أرقام أسعار موثّقة.
- **تحذيرات قانونية/امتثال:** (1) الكود مُعلَّم UNVERIFIED على سلسلة حقيقية — اختبره بمبلغ صغير على Testnet/مبلغ رمزي قبل الاعتماد. (2) استلام عملات رقمية مقابل خدمات كوسيط تجاري قد يستدعي التزامات ضريبية/AML في بريطانيا وفي العراق — **استشر محاسباً/محامياً** قبل التشغيل التجاري [غير مُتحقَّق]. (3) عنوان العقد (USDT contract) على TRON يجب أن تتحقق منه من مصدر رسمي (Tether / TRONSCAN) وتنسخه بنفسك، لا من وسيط.
- **متغيرات البيئة [من الكود، وكلها مطلوبة معاً ما عدا المفتاح]:**
  - `FF_PAYMENTS_PROVIDER=usdt_tron` (الافتراضي `mock`؛ الإنتاج يرفض `mock`)
  - `FF_PAYMENTS_USDT_RECEIVE_ADDRESS` (عنوان عام)
  - `FF_PAYMENTS_USDT_CONTRACT`
  - `FF_PAYMENTS_USDT_EXPLORER_URL` (يجب `https://`)
  - `FF_PAYMENTS_USDT_EXPLORER_API_KEY` (مفتاح TronGrid)
  - `FF_PAYMENTS_WEBHOOK_SECRET_USDT_TRON` و`FF_PAYMENTS_ADMIN_TOKEN` (يُولَّدان عشوائياً بـ `openssl rand -hex 32`)
  - اختياري: `FF_PAYMENTS_USDT_MIN_CONFIRMATIONS` (الافتراضي 20)
- **مفتاح الإيقاف:** `FF_PAYMENTS_PROVIDER=off` (يعطّل إنشاء الفواتير).

---

## 5. مساعد الذكاء الاصطناعي (LLM) — الأولوية 4

- **المحوّل:** `ff_assistant/llm.py` (يستدعي `POST {base}/v1/messages` بصيغة Anthropic Messages مع ترويسات `x-api-key` و`anthropic-version`) [من الكود].
- **المزوّد:** Anthropic API (Claude) أو أي بوابة متوافقة مع صيغة Messages عبر `FF_ASSISTANT_LLM_BASE_URL`.
- **ما المطلوب:** حساب مطوّرين (Console) ومفتاح API وطريقة دفع. **تحقّق من توفّر الخدمة في العراق وطرق الدفع المقبولة** [غير مُتحقَّق] — لهذا يفيدك الكيان البريطاني وPayoneer.
- **الكلفة:** تُدفع بالاستهلاك (tokens)؛ لا أذكر أرقاماً غير موثّقة. الكود يقيّد الاستهلاك: `FF_ASSISTANT_LLM_MAX_TOKENS` و`FF_ASSISTANT_LLM_MAX_INPUT_CHARS` و`FF_ASSISTANT_LLM_TIMEOUT_S` وحصة يومية للمستخدم `FF_ASSISTANT_QUOTA_PER_DAY`. اختر نموذجاً صغيراً رخيصاً عبر `FF_ASSISTANT_LLM_MODEL` (الافتراضي في الكود `claude-haiku-5-5` — تأكد أنه اسم صالح حالياً).
- **تحذير خصوصية:** نصوص المستخدمين ترسل لطرف ثالث؛ حدّث `PRIVACY_POLICY` وأخبر المستخدمين. المساعد مصمّم ألا يخترع أرقاماً (الأرقام تأتي من الخدمات).
- **متغيرات البيئة [من الكود]:** `FF_ASSISTANT_LLM=anthropic` (القيم: `off` | `mock` | `anthropic`؛ الافتراضي `off`) ، `FF_ASSISTANT_LLM_API_KEY` ، `FF_ASSISTANT_LLM_MODEL` ، `FF_ASSISTANT_LLM_BASE_URL` (اختياري) ، `FF_ASSISTANT_LLM_REWRITE=true` (اختياري: إعادة صياغة النبرة).
- **مفتاح الإيقاف:** `FF_ASSISTANT_LLM=off`.

---

## 6. مصادر المنتجات/الموردين (Sourcing) — القسم الأهم تجارياً لكن الأطول زمناً

عام لكل المحوّلات هنا: لا يعمل المحوّل الحقيقي إلا إذا وُضع معرّفه في `FF_SOURCING_ADAPTERS` **و**ضُبطت مفاتيحه. مفتاح الإيقاف العام: `FF_SOURCING_KILL_SWITCH=1`؛ ولكل محوّل مفتاح بالصيغة `FF_SOURCING_<ID>_DISABLED=1` (مثل `FF_SOURCING_ALIBABA_DISABLED`) [من الكود: `http_base.py`]. الـ mock يبقى احتياطاً عند الفشل. إعدادات مشتركة: `FF_SOURCING_ADAPTER_TIMEOUT_S` ، `FF_SOURCING_MIN_REQUEST_INTERVAL_S` (الأدنى 3) ، `FF_SOURCING_CACHE_TTL_S`.

### 6.1 AliExpress Affiliate API — (معرّف المحوّل: `aliexpress`)
- **البرنامج الرسمي:** AliExpress Open Platform (developers.aliexpress.com) + برنامج AliExpress Portals/Affiliate للحصول على `tracking_id`. [غير مُتحقَّق: لم تُقرأ الصفحة]
- **المطلوب:** تسجيل مطوّر، إنشاء تطبيق (App Key/Secret)، حساب شركاء للحصول على tracking id؛ قد تتطلب الموافقة وصفاً للتطبيق/الموقع ومراجعة. اسم الطريقة في الكود `aliexpress.affiliate.product.query` — **غير مُتحقَّق**.
- **ملاحظة تجارية:** AliExpress سوق تجزئة (MOQ=1) وليس مصانع جملة؛ يصلح لمنتجات صغيرة لا خطوط إنتاج.
- **قانوني:** استخدام روابط الشركاء بحسب شروط البرنامج؛ لا تعرض محتواً مخالفاً لشروط العرض/التخزين المؤقت للمزوّد؛ حدّ 3 ثوانٍ.
- **env [من الكود]:** `FF_SOURCING_ALIEXPRESS_APP_KEY` ، `FF_SOURCING_ALIEXPRESS_APP_SECRET` ، `FF_SOURCING_ALIEXPRESS_TRACKING_ID` ، (اختياري) `FF_SOURCING_ALIEXPRESS_API_BASE` ؛ فعّل بـ `FF_SOURCING_ADAPTERS=aliexpress`.
- **إيقاف:** `FF_SOURCING_ALIEXPRESS_DISABLED=1` أو `FF_SOURCING_KILL_SWITCH=1`.

### 6.2 Alibaba.com Open Platform — (معرّفان: `alibaba_openapi` (الأحدث) و`alibaba`)
- **البرنامج الرسمي:** Alibaba.com Open Platform (open.alibaba.com) — واجهات ICBU. [غير مُتحقَّق: لم تُقرأ الصفحة]. قد توجد برامج منفصلة (مثل واجهات المشتري/الدروبشيبنغ أو الشركاء) — لا أستطيع تأكيد أي منها يمنح **بحث منتجات للمشتري**؛ بعض الواجهات مخصصة للمورّدين (إدارة منتجاتهم) لا للبحث العام. هذا أكبر خطر: قد لا يتوفر ما يحتاجه المحوّل لحسابك.
- **المطلوب (محتمل، غير مُتحقَّق):** تسجيل مطوّر، تطبيق، تفويض OAuth (Access Token)، وربما توثيق شركة. الكيان البريطاني سيسهّل.
- **قانوني:** الالتزام باتفاقية المنصة؛ لا كشط لموقع alibaba.com؛ احترام الحصص (quotas).
- **env [من الكود]:** `FF_SOURCING_ALIBABA_APP_KEY` ، `FF_SOURCING_ALIBABA_APP_SECRET` ، `FF_SOURCING_ALIBABA_ACCESS_TOKEN` (للمحوّل `alibaba_openapi`) ، (اختياري) `FF_SOURCING_ALIBABA_API_BASE` ؛ فعّل بـ `FF_SOURCING_ADAPTERS=alibaba_openapi`.
- **إيقاف:** `FF_SOURCING_ALIBABA_OPENAPI_DISABLED=1` (وللمحوّل `alibaba`: `FF_SOURCING_ALIBABA_DISABLED=1`) أو `FF_SOURCING_KILL_SWITCH=1`.
- **بديل أسرع:** المحوّل العام `licensed_rest` (انظر 6.5) إن أعطتك شركة مرخِّصة بيانات Alibaba.

### 6.3 Made-in-China.com — (معرّف: `made_in_china`)
- **الوضع:** لا نعرف API بحث عاماً؛ الكود يفترض **تغذية مرخّصة (licensed feed)** عبر شراكة. [من الكود + غير مُتحقَّق]. الطريق: التواصل مع قسم الشراكات/الأعمال في الموقع لطلب تغذية بيانات أو ترخيص.
- **خيار الصفحات العامة:** `FF_SOURCING_MIC_ALLOW_PUBLIC_PAGES=true` لا يُفعَّل إلا بعد أن يراجع إنسان شروط الاستخدام ويتأكد أن `robots.txt` يسمح؛ الأفضل **عدم استخدامه** حتى تحصل على إذن مكتوب.
- **env [من الكود]:** `FF_SOURCING_MIC_API_BASE` ، `FF_SOURCING_MIC_API_KEY` ، `FF_SOURCING_MIC_ALLOW_PUBLIC_PAGES` ؛ فعّل بـ `FF_SOURCING_ADAPTERS=made_in_china`.
- **إيقاف:** `FF_SOURCING_MADE_IN_CHINA_DISABLED=1` أو `FF_SOURCING_KILL_SWITCH=1`.

### 6.4 1688.com — (معرّف: `source_1688`)
- **البرنامج:** منصة 1688 المفتوحة (open.1688.com). [غير مُتحقَّق]. 1688 سوق محلي في الصين؛ الوصول الرسمي غالباً يتطلب كياناً/هوية صينية وحساب Alipay صيني [غير مُتحقَّق]. موردو 1688 قد لا يصدّرون. الأرجح عملياً: مورّد/وكيل مرخّص في الصين يعطيك بيانات، أو مجمّع بيانات مرخّص عبر `licensed_rest`.
- **env [من الكود]:** `FF_SOURCING_S1688_APP_KEY` ، `FF_SOURCING_S1688_APP_SECRET` ، (اختياري) `FF_SOURCING_S1688_API_BASE` ؛ فعّل بـ `FF_SOURCING_ADAPTERS=source_1688`.
- **إيقاف:** `FF_SOURCING_SOURCE_1688_DISABLED=1` أو `FF_SOURCING_KILL_SWITCH=1`. (اسم المتغير مبني على المعرّف `source_1688` حسب `http_base.py`.)

### 6.5 مزوّد REST مرخّص عام (Licensed REST) — الأنسب إن اشتريت بيانات من مجمّع
- **المحوّل:** `licensed_rest.py` — يُعرَّف بملف mapping JSON (انظر `services/sourcing/examples/licensed` و`docs/decisions/sourcing-licensed-provider.md`)؛ الأمثلة الوهمية مرفوضة افتراضياً.
- **env [من الكود]:** `FF_SOURCING_LICENSED_MAPPINGS` (مسارات ملفات mapping) + المتغير الذي يسمّيه ملفك في `key_env` + `FF_SOURCING_ADAPTERS=<id>`. `FF_SOURCING_LICENSED_ALLOW_EXAMPLE` اتركه فارغاً.
- **إيقاف:** `FF_SOURCING_<ID>_DISABLED=1` أو `FF_SOURCING_KILL_SWITCH=1`.
- **قانوني:** اقرأ عقد المزوّد: حقوق التخزين المؤقت وإعادة العرض والتجارة.

### 6.6 Global Sources
- لا يوجد محوّل في المستودع حالياً. إن أردت إضافته فاطلب من المزوّد تغذية/API مرخّصة عبر شراكة [غير مُتحقَّق من وجود API عام]، ثم يُضاف عبر `licensed_rest` دون كتابة كود جديد.

---

## 7. تتبّع الشحنات (Tracking) — الأولوية 7

- **المحوّلات:** `HttpContainerProvider` (حاوية/بوليصة) و`HttpAwbProvider` (شحن جوي) و`HttpVesselPositionProvider` (موقع السفينة AIS) في `services/tracking/src/ff_tracking/adapters/http.py`؛ والمسار يقرأ رمز DCSA إن كان الرد بصيغة DCSA [من الكود].
- **الخيارات (كلها غير مُتحقَّق من شروطها وأسعارها):**
  1. **DCSA Track & Trace**: معيار (standard) تنفّذه شركات الملاحة الأعضاء، وليس خدمة مركزية واحدة. الوصول عادةً عبر بوابة مطوّري كل ناقل (Maersk، MSC، CMA CGM، Hapag-Lloyd…) بتسجيل وحساب عميل. [المرجع: https://dcsa.org/standards/track-and-trace — لم يُقرأ]
  2. **مجمّع تتبع مرخّص** (مثل TrackingMore أو شبيه): مفتاح واحد لعدّة ناقلين؛ عادةً بخطط مدفوعة. [غير مُتحقَّق؛ لم أتحقق من أي مزوّد]
  3. **AIS للسفن:** مزوّد بيانات مرخّص رسمياً فقط؛ لا تكشط مواقع مثل MarineTraffic.
  4. **الشحن الجوي (AWB):** واجهات شركات الطيران/ مجمّع مرخّص.
- **تحذير:** ممنوع كشط مواقع الناقلين أو مواقع AIS (الكود يمنعه بالتصميم). ضع حدّ الاستدعاء الأدنى 3 ثوانٍ. الاستعلام يجب أن يتم بمرجع الشحنة الذي يملكه المستخدم.
- **env [من الكود]:**
  - `FF_TRACKING_PROVIDER=http` (الافتراضي `mock`)
  - الحاوية/البوليصة: `FF_TRACKING_CONTAINER_BASE_URL` و`FF_TRACKING_CONTAINER_API_KEY`
  - الجوي: `FF_TRACKING_AWB_BASE_URL` و`FF_TRACKING_AWB_API_KEY`
  - السفن: `FF_TRACKING_VESSEL_BASE_URL` و`FF_TRACKING_VESSEL_API_KEY`
  - ضبط: `FF_TRACKING_HTTP_MIN_INTERVAL_SECONDS` (الأدنى 3) ، `FF_TRACKING_HTTP_CACHE_TTL_SECONDS` ، `FF_TRACKING_FALLBACK_TO_MOCK` (افتراضي true) ، `FF_TRACKING_REFRESH_JOB_ENABLED` و`_INTERVAL_HOURS`
- **إيقاف:** `FF_TRACKING_KILL_SWITCH=1` (عام) أو `FF_TRACKING_CONTAINER_DISABLED=1` / `FF_TRACKING_AWB_DISABLED=1` / `FF_TRACKING_VESSEL_DISABLED=1`.

---

## 8. أسعار الشحن الحيّة (Freight rates) — الأولوية 8

- **المحوّل:** `HttpFreightProvider` في `services/logistics/src/ff_logistics/adapters/freight.py` (هيكل على طراز Freightos: `GET {url}/shippingCalculator` مع ترويسة `x-apikey`) — **غير مُتحقَّق** [من الكود].
- **المزوّد المحتمل:** Freightos أو مزوّد أسعار شحن آخر؛ غالباً اتفاقية تجارية/شراكة وليست تسجيلاً مجانياً [غير مُتحقَّق]. بدونه يعمل محرك التكلفة بجداول داخلية مُقدَّرة (estimates بنطاق).
- **قانوني:** رخصة استخدام الأسعار وعرضها للمستخدمين؛ الأسعار تقديرية وليست عروضاً ملزمة — أبقِ التسمية "تقدير".
- **env [من الكود]:** `FF_LOGISTICS_FREIGHT_PROVIDER=http` ، `FF_LOGISTICS_FREIGHT_URL` ، `FF_LOGISTICS_FREIGHT_API_KEY` ، (اختياري) `FF_LOGISTICS_FREIGHT_MIN_INTERVAL_S` و`_CACHE_TTL_SECONDS` و`_MAX_CALLS_PER_QUOTE`.
- **إيقاف:** `FF_LOGISTICS_FREIGHT_DISABLED=1` أو `FF_LOGISTICS_KILL_SWITCH=1` (يعود إلى الجداول الداخلية).
- **ملاحظة:** سوق شركات الشحن الداخلية (`services/freight`) لا يستدعي مزوّداً خارجياً؛ هو سوق ذاتي (طلبات وعروض) ولا يحتاج تقديماً.

---

## 9. الجغرافيا والثقة وغيرها

- **الجغرافيا (`FF_LOGISTICS_GEO_PROVIDER`):** تعمل ببيانات محلية داخلية (`services/geo`)؛ لا مزوّد خارجياً مطلوباً حالياً.
- **الثقة (Trust):** `AlibabaSignalsAdapter` و`MadeInChinaSignalsAdapter` في `services/trust/.../adapters/real.py` مجرد هياكل معطّلة (ترمي `AdapterDisabled`). لا تقدّم لشيء الآن؛ تعتمد على موافقة مصادر 6.2 و6.3 لاحقاً. التحقق من الموردين يمكن أن يعتمد على وثائقهم (verification documents) داخل التطبيق.
- **تخزين الصور (S3):** `FF_MEDIA_STORAGE_BACKEND=s3` مع `FF_MEDIA_S3_*` — مُعلَّم UNVERIFIED في المستودع؛ احتفظ بـ `local` حتى يُختبر.

---

## 10. خطة العمل المقترحة (أسبوعياً)

1. **الآن (بلا شركة):** FX ← FCM ← محفظة USDT + مفتاح TronGrid (اختبار بمبلغ صغير).
2. **بالتوازي:** قدّم على AliExpress Affiliate وAlibaba Open Platform (قد تُطلب بيانات شركة؛ اذكر أن الشركة قيد التأسيس).
3. **بعد الشركة البريطانية:** حساب LLM مدفوع، تقديمات الناقلين/المجمّعين، تفاوض تغذية Made-in-China، مزوّد أسعار الشحن.
4. **قبل أي تفعيل حقيقي:** سجّل استجابة حقيقية واحدة لكل مزوّد، استبدل الـ fixtures، شغّل `make test`، ثم فعّل محوّلاً واحداً مع إبقاء مفتاح الإيقاف جاهزاً.

## 11. جدول المتغيرات السريع (للتفعيل / للإيقاف)

| المحوّل | تفعيل | إيقاف |
|---|---|---|
| FX | `FF_LOGISTICS_FX_PROVIDER=ecb` | `=mock` |
| Push | `FF_NOTIFY_PUSH=fcm` | `=off` |
| USDT | `FF_PAYMENTS_PROVIDER=usdt_tron` | `=off` |
| LLM | `FF_ASSISTANT_LLM=anthropic` | `=off` |
| مصادر المنتجات | `FF_SOURCING_ADAPTERS=<id>` | `FF_SOURCING_<ID>_DISABLED=1` / `FF_SOURCING_KILL_SWITCH=1` |
| التتبع | `FF_TRACKING_PROVIDER=http` | `FF_TRACKING_KILL_SWITCH=1` |
| الشحن | `FF_LOGISTICS_FREIGHT_PROVIDER=http` | `FF_LOGISTICS_FREIGHT_DISABLED=1` / `FF_LOGISTICS_KILL_SWITCH=1` |
