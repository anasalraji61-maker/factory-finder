# Privacy Policy / سياسة الخصوصية — Factory Finder (مُوَرِّد)

> **DRAFT. NOT LEGAL ADVICE. MUST BE REVIEWED BY A QUALIFIED LAWYER BEFORE PUBLICATION.**
> **مسودة. ليست استشارة قانونية. يجب مراجعتها من محامٍ مختص قبل النشر.**
>
> Facts below come from the code (`services/gateway/src/ff_gateway/domain/privacy.py`, each service's `privacy.py`, `docs/SECURITY.md`, `docs/OPS.md`, `docs/decisions/account-deletion.md`). Items marked **[PLANNED/OPTIONAL]** are not active by default. Items in `[BRACKETS]` are placeholders to fill. Re-verify every fact against the release build.

Last updated / آخر تحديث: [DATE]
Operator / الجهة المشغّلة: [COMPANY NAME] · [COMPANY REGISTRATION NO.] · [ADDRESS] · [CONTACT EMAIL] · [DATA PROTECTION CONTACT]

---

## العربية

### 1. من نحن
[اسم الشركة] ("نحن") تشغّل تطبيق مُوَرِّد (Factory Finder)، وهو منصة وساطة تربط المشترين بالموردين وتقدّر كلفة الاستيراد الكاملة. العنوان: [العنوان]. للتواصل بشأن الخصوصية: [البريد].

### 2. البيانات التي نجمعها
| الفئة | ما نخزّنه | ملاحظات |
|---|---|---|
| الحساب | البريد، كلمة المرور (مجزّأة بـ bcrypt فقط)، الاسم، الشركة، الهاتف، الدور، الوجهة الافتراضية، اللغة، عملة العرض، حالة توثيق البريد | الاسم والبريد والهاتف اختيارية جزئياً حسب الحقل |
| الجلسات | رموز التحديث (مجزّأة) وإصدار الرمز | تنتهي عند تسجيل الخروج أو الحذف |
| ادعاء حساب مورد | معرّف المورد وحالة الطلب وقرار الإدارة | |
| الإعلانات والطلبات والعروض والتقييمات | ما تنشره | تُفحص النصوص آلياً لرفض الروابط وأرقام الهاتف والسلع المحظورة |
| الرسائل | نصوص المحادثات ومراجع المرفقات وقوائم الحظر | تُرسل عبر اتصال WebSocket مرخّص بتذكرة قصيرة العمر |
| الوسائط | الصور المرفوعة (تُعاد ترميزها وتُزال بياناتها الوصفية بما فيها الموقع)، حصة التخزين | |
| وثائق التحقق (للموردين) | وثائق الأعمال | خاصة دائماً؛ يراها صاحبها والمشرفون أو عبر رابط موقّع قصير العمر |
| الفواتير والعمولات | المبالغ والعملة والحالة ومعرّف الصفقة والدافع والمستفيد وملاحظة الدافع الحرة وعنوان عام لمحفظة الاستلام ومعرّف المعاملة | لا نخزّن أرقام بطاقات ولا مفاتيح خاصة |
| الشحن | طلبات الشحن وعروض المخلّصين وتقييماتهم والشحنات المتتبَّعة (أرقام حاويات/بوالص) | |
| التنبيهات | قوائم المراقبة والتنبيهات وتفضيلات الإشعارات وأجهزة الإشعار (رمز الجهاز) | رمز الجهاز يُحفظ فقط إن فعّلت الإشعارات |
| المحتوى الاجتماعي | المنشورات والتعليقات والإعجابات والمتابعات والبلاغات | |
| المساعد الذكي | عدّاد استخدام فقط؛ لا نخزّن المحادثات | عند تفعيل نموذج لغوي خارجي **[مخطط/اختياري]** يُرسل نص السؤال (حتى 1500 حرف) إلى المزوّد |
| سجلات الخادم | معرّف الطلب، الطريقة، المسار، الحالة، المدة، معرّف المستخدم | لا كلمات مرور ولا رموز ولا نصوص استعلام ولا محتوى الطلبات |
| سجل التدقيق | معرّف مستخدم مبهم، نوع الحدث، عدّادات، معرّف الطلب | دون بريد أو هاتف أو اسم |

**لا نجمع:** موقع الجهاز، ولا بيانات تحليلات أو إعلانات أو تتبّع عبر التطبيقات، ولا أرقام البطاقات. لا نستخدم SDK تحليلات أو إعلانات في التطبيق. [تحقق قبل الإصدار، خصوصاً عند إضافة Firebase/FCM.]

### 3. كيف نستخدم البيانات والأساس القانوني
تشغيل الحساب والخدمة؛ البحث وحساب الكلفة التقديرية؛ ربط المشترين بالموردين وتسجيل الصفقات والعمولات؛ التحقق ومنع الاحتيال والإساءة (قد تُحجب المنشورات تلقائياً)؛ التنبيهات؛ الدعم؛ الالتزامات القانونية والمحاسبية. الأساس القانوني: [العقد / المصلحة المشروعة / الموافقة / الالتزام القانوني — يحدده المحامي حسب القانون المطبق].

### 4. المشاركة
- **الأطراف الأخرى في الصفقة** ترى ما تنشره وملفك العام ومستوى التوثيق ورسائلك معهم. ملاحظة الدافع في الفاتورة لا يراها إلا الدافع.
- **مزودو خدمات (كلهم [مخطط/اختياري] ولا تعمل افتراضياً):**
  - مزود أسعار الصرف (ECB أو رابط FX قابل للضبط): نرسل طلب أسعار عامة دون بيانات شخصية.
  - مزود الإشعارات Firebase Cloud Messaging: رمز الجهاز ونص الإشعار.
  - مزودو تتبع الشحنات (حاويات/بوالص/سفن) المرخّصون: رقم الحاوية أو البوليصة الذي تتتبعه.
  - مزودو أسعار الشحن ومصادر الموردين (واجهات مرخّصة): استعلامات البحث دون هوية.
  - الدفع بعملة USDT على شبكة TRON ومستكشف السلسلة: عنوان المحفظة العام ومعرّف المعاملة (بيانات عامة على السلسلة).
  - نموذج لغوي للمساعد (اختياري، افتراضياً مغلق): نص السؤال.
  - الاستضافة والبريد والنسخ الاحتياطي: [أسماء المزودين].
- جهات قانونية عند الطلب النظامي.
- لا نبيع بياناتك ولا نستخدمها للإعلانات.

### 5. النقل الدولي
قد تُعالج البيانات خارج بلدك: [الدول]. الضمانات: [ضمانات/بنود تعاقدية — يحددها المحامي].

### 6. الاحتفاظ
- **حسابك:** طالما الحساب نشط.
- **سجلات تُحذف دورياً (افتراضات الكود، قابلة للضبط):** إشارات الطلب المرصودة والمسودات المرفوضة 90 يوماً؛ تنبيهات الإشعارات 180 يوماً وسجلات التسليم 30 يوماً؛ أحداث الـ webhook للدفع وأحداث الإرسال المسلَّمة 180 يوماً؛ محاولات الفواتير المنتهية/الفاشلة 365 يوماً؛ تاريخ الأسعار وعدّادات الاستخدام اليومية 400 يوماً؛ بلاغات الثقة المرفوضة/القديمة 365 يوماً ولقطات الدرجات 730 يوماً.
- **تُحفظ حتى بعد الحذف لأسباب قانونية/محاسبية:** الفواتير ودفتر الحسابات ومحاولات الدفع والصفقات وأحداثها والعروض المقبولة (بمعرّفات مستعارة فقط)؛ سجل التوثيق وملفات الأعمال التي يخضع لها المورد؛ بلاغات الإساءة (بعد إخفاء هوية المُبلِّغ)؛ نصوص الرسائل في المحادثات المشتركة محجوبة النص الخاص بك؛ سجل حذف الحساب (معرّفات مبهمة).
- **النسخ الاحتياطية:** تختفي البيانات المحذوفة بعد دورة التدوير العادية: [المدة].
- مدة الاحتفاظ بالسجلات المالية: [المدة حسب القانون].

### 7. حقوقك
- **التصدير:** من التطبيق/الواجهة `GET /v1/me/export` يعيد ملف JSON بملفك وما تحتفظ به كل خدمة (محدود الحجم؛ إن تعذّرت خدمة يُذكر ذلك في الملف).
- **الحذف:** `DELETE /v1/me` بعد إعادة إدخال كلمة المرور. يُنهي جميع الجلسات، ويُخفي هوية صفّ حسابك (بريد/هاتف/اسم/شركة)، ثم يُرسل أوامر محو لكل خدمة تحتفظ ببياناتك مع إعادة المحاولة حتى النجاح. قد تُضاف فترة سماح [N] يوماً (تسجيل دخول صحيح خلالها يلغي الحذف). **شاشة الحذف في التطبيق [غير متوفرة بعد / رابط الويب: URL].**
- التصحيح والاعتراض وسحب الموافقة: عبر الحساب أو [البريد].
- استثناءات الحذف مبيّنة في البند 6.
- حق الشكوى لدى الجهة الرقابية: [الجهة].

### 8. الأمان
HTTPS، كلمات مرور مجزّأة، رموز وصول قصيرة العمر (15 دقيقة) ورموز تحديث تُستعمل مرة واحدة، وصول خاص للوثائق، حدود معدّل الطلبات، إخفاء المعلومات الحساسة من السجلات. لا يوجد نظام آمن بالكامل. الإبلاغ عن ثغرة: [البريد].

### 9. الأطفال
الخدمة للأعمال ولمن بلغ 18 عاماً فأكثر.

### 10. التغييرات
سنخطرك بالتغييرات الجوهرية عبر التطبيق أو البريد.

---

## English

### 1. Who we are
[COMPANY NAME] ("we") operates the Factory Finder (مُوَرِّد) app, an intermediary marketplace that connects buyers with suppliers and estimates full import cost. Address: [ADDRESS]. Privacy contact: [EMAIL].

### 2. Data we collect
| Category | What is stored | Notes |
|---|---|---|
| Account | email, password (bcrypt hash only), name, company, phone, role, default destination, language, display currency, email-verified flag | |
| Sessions | hashed refresh tokens, token version | removed on logout/deletion |
| Supplier claim | supplier id, claim status, admin decision | |
| Listings, requests, offers, reviews | what you post | free text is screened to reject links, phone numbers and prohibited goods |
| Messages | conversation text, attachment references, block lists | chat sockets use short-lived single-use tickets |
| Media | uploaded images (re-encoded, metadata incl. GPS stripped), storage quota | |
| Verification documents (suppliers) | business documents | always private: owner, admins, or short-lived signed URL |
| Invoices and commissions | amount, currency, status, deal id, payer and payee ids, payer's free-text memo, public receiving wallet address, transaction id | no card numbers, no private keys |
| Freight and shipments | shipment requests, forwarder quotes and ratings, tracked container/AWB numbers | |
| Alerts | watchlists, alerts, notification preferences, device push token | token stored only if you enable push |
| Social content | posts, comments, likes, follows, reports | |
| Assistant | usage counter only; conversations are not stored | if an external LLM is enabled **[PLANNED/OPTIONAL]**, the question text (up to 1,500 characters) goes to that provider |
| Server logs | request id, method, path, status, duration, user id | never passwords, tokens, query strings or request bodies |
| Audit trail | opaque user id, event name, counters, request id | no email, phone or name |

**We do not collect:** device location, analytics/advertising/cross-app tracking data, or card numbers. There is no analytics or ad SDK in the app. [Re-verify before release, especially if Firebase/FCM is added.]

### 3. Purposes and legal bases
Operate your account and the service; search and estimate costs; connect buyers and suppliers and record deals and commissions; verification and fraud/abuse prevention (automated screening may block posts); alerts; support; legal and accounting duties. Legal bases: [contract / legitimate interests / consent / legal obligation — to be set by counsel for the applicable law].

### 4. Sharing
- **Counterparties** see what you post, your public profile, verification level and your messages with them. The payer's invoice memo is visible only to the payer.
- **Service providers (all **[PLANNED/OPTIONAL]**, off by default):**
  - FX rates provider (ECB or configurable URL): public rate requests, no personal data.
  - Firebase Cloud Messaging push: device token and notification text.
  - Licensed shipment-tracking providers (container / AWB / vessel): the tracking number you follow.
  - Licensed freight-rate and supplier-source APIs: search queries, not identities.
  - USDT-on-TRON payments and blockchain explorer: public wallet address and transaction id (public on-chain data).
  - LLM provider for the assistant (off by default): question text.
  - Hosting, email, backups: [PROVIDER NAMES].
- Authorities where legally required.
- We do not sell your data or use it for advertising.

### 5. International transfers
Data may be processed outside your country: [COUNTRIES]. Safeguards: [TO BE SET BY COUNSEL].

### 6. Retention
- **Active account:** while the account exists.
- **Routine purges (code defaults, configurable):** demand signals and rejected drafts 90 days; notification alerts 180 days and delivery rows 30 days; payment webhook and delivered outbox events 180 days; attempts on expired/failed invoices 365 days; price history and daily usage counters 400 days; rejected/stale trust reports 365 days and score snapshots 730 days.
- **Kept after deletion for legal/accounting reasons:** invoices, ledger, payment attempts, deals, deal events and accepted offers (pseudonymous ids only); supplier verification records and audit trail; abuse reports (reporter anonymized); message threads shared with counterparties (your own text is blanked); account-deletion audit (opaque ids).
- **Backups:** deleted data leaves backups on normal rotation: [PERIOD].
- Financial records retention period: [PERIOD PER LAW].

### 7. Your rights
- **Export:** `GET /v1/me/export` returns a JSON bundle of your profile and what each service holds (size-capped; a failing service is flagged as partial).
- **Erasure:** `DELETE /v1/me` after re-entering your password. It ends all sessions, anonymizes your account row (email, phone, name, company), and fans out erasure to every service holding your data, retried until done. An optional grace period of [N] days applies (a correct login cancels it). **The in-app deletion screen is [NOT YET AVAILABLE / web URL: URL].**
- Correction, objection, withdrawal of consent: via your account or [EMAIL].
- Exceptions to erasure are in section 6.
- Right to complain to the regulator: [AUTHORITY].

### 8. Security
HTTPS, hashed passwords, 15-minute access tokens and single-use refresh tokens, private document access, rate limits, sensitive data kept out of logs. No system is fully secure. Report a vulnerability: [EMAIL].

### 9. Children
For businesses and users aged 18 and over.

### 10. Changes
We will notify you of material changes in the app or by email.
