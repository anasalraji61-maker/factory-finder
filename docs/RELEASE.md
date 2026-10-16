# إصدار تطبيق أندرويد / Android Release Guide

## العربية

### 1. إنشاء مفتاح التوقيع (مرة واحدة فقط)
نفّذ على جهازك (وليس في المستودع، فالمستودع عام):

```bash
keytool -genkey -v -keystore upload-keystore.jks -keyalg RSA -keysize 2048 \
  -validity 10000 -alias upload
```

- احفظ ملف `upload-keystore.jks` وكلمتي المرور في مكانين آمنين (مدير كلمات مرور + نسخة احتياطية). ضياعه يعني طلب إعادة ضبط مفتاح الرفع من Google.
- فعّل **Play App Signing** عند أول رفع؛ المفتاح هنا هو مفتاح الرفع فقط.
- لا تضعه في Git أبداً (`*.jks` و`key.properties` ممنوعان).

### 2. إضافة الأسرار في GitHub
Settings ← Secrets and variables ← Actions ← New repository secret:

| السر | القيمة |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | ناتج `base64 -w0 upload-keystore.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | كلمة مرور الـ keystore |
| `ANDROID_KEY_ALIAS` | `upload` (أو ما اخترته) |
| `ANDROID_KEY_PASSWORD` | كلمة مرور المفتاح |

إن غاب أي سر من الأربعة يُبنى APK موقّع بمفتاح debug للاختبار الداخلي فقط (لا يصلح للمتجر ولا يُنتج AAB).

### 3. تشغيل الـ workflow
Actions ← **mobile-release** ← Run workflow، ثم املأ:
- `api_base_url`: عنوان الخادم بـ **https** (يُمرَّر كـ `--dart-define=FF_API_BASE_URL`؛ وضع المحاكاة يُطفأ بـ `FF_MOCK=false`).
- `build_name` (مثل `0.1.0`) و`build_number` (رقم صحيح يزيد في كل رفع). اتركهما فارغين لاستخدام `pubspec.yaml`.
- `build_aab`: لبناء حزمة المتجر.

الناتج في Artifacts: `factory-finder-apk-*` و`factory-finder-aab-signed` (30 يوماً). يُحذف ملف المفتاح من العامل بعد البناء.

### 4. قواعد الإصدار
- `version: X.Y.Z+N` في `apps/mobile/pubspec.yaml`: `X.Y.Z` اسم الإصدار الظاهر للمستخدم (SemVer)، و`N` رقم الإصدار (versionCode).
- `N` يجب أن يزيد في كل رفع إلى Play ولا يُعاد استخدامه أبداً.
- ارفع Y للميزات وZ للإصلاحات وX للتغييرات الكبيرة.
- المدخلان `build_name`/`build_number` في الـ workflow يتغلّبان على pubspec؛ اختر مصدراً واحداً واتبعه.
- ضع وسماً (tag) لكل إصدار منشور (يقوم به المنسّق، لا الوكلاء).

### 5. قائمة التحقق لـ Google Play
- [ ] **رابط سياسة الخصوصية** عام وفعّال (من `docs/PRIVACY_POLICY.draft.md` بعد مراجعة محامٍ وملء الحقول بين [ ]).
- [ ] **رابط حذف الحساب/البيانات** على الويب + شاشة حذف الحساب داخل التطبيق (غير موجودة حالياً، مطلوبة قبل التقديم).
- [ ] **نموذج أمان البيانات** (مطابق لما يجمعه التطبيق فعلاً، انظر `docs/STORE_LISTING.md` §6):
  - تُجمع: البريد، الاسم/الشركة/الهاتف (اختياري)، معرّف المستخدم، الصور (اختياري، تُزال بيانات الموقع EXIF)، وثائق التحقق (اختياري)، الرسائل، محتوى المستخدم (إعلانات/طلبات/عروض/تقييمات)، بيانات مالية وصفية فقط (لا أرقام بطاقات)، رمز الجهاز للإشعارات إن فُعّلت.
  - لا تُجمع: الموقع، التحليلات، سجلات الأعطال داخل التطبيق.
  - لا تُشارك مع أطراف ثالثة ولا تُباع ولا تُستخدم للإعلانات (FCM مزود معالجة فقط إن فُعّل).
  - مشفّرة أثناء النقل: نعم (HTTPS). طلب الحذف: مدعوم.
  - أعد المراجعة عند إضافة أي SDK (Firebase وغيره) أو تفعيل الدفع.
- [ ] **تصنيف المحتوى (IARC):** محتوى مستخدمين وتفاعل (دردشة)، بلا عنف أو قمار أو محتوى ناضج، بلا موقع دقيق. الحد الأدنى للعمر 18 (استخدام تجاري). أجب بصدق.
- [ ] **أيقونة التطبيق** 512×512 PNG، وأيقونة التطبيق داخل الحزمة (الافتراضية من Flutter يجب استبدالها).
- [ ] **صورة الميزة** 1024×500.
- [ ] **لقطات الشاشة** (2 على الأقل، حتى 8، عربي RTL أولاً ثم إنجليزي): الرئيسية، نتائج البحث، تفاصيل الإعلان وعوامل الثقة، صفحة المورد والتوثيق، حاسبة التكلفة الواصلة، الطلبات والعروض، الدردشة، تتبع الشحنة، المساعد، الإعدادات. استخدم بيانات تجريبية ولا تعرض شعارات لا تملكها.
- [ ] الفئة (Business) والوصف والكلمات المفتاحية (`docs/STORE_LISTING.md`).
- [ ] حساب تجريبي لمراجعي المتجر وشرح وضع المحاكاة مقابل الخادم الحي، مع التنويه بأن الجمارك والكلفة تقديرية.
- [ ] الأذونات المعلنة: الإنترنت، الكاميرا، قراءة الصور (اختيارية)؛ برّرها في نموذج الأذونات.
- [ ] اختبار داخلي ثم مغلق قبل الإنتاج (حسابات المطورين الشخصية الجديدة لها متطلبات اختبار مغلق؛ تحقق من الشروط الحالية).

---

## English

### 1. Create the signing keystore (once)
Run locally, never inside the repo (it is public):

```bash
keytool -genkey -v -keystore upload-keystore.jks -keyalg RSA -keysize 2048 \
  -validity 10000 -alias upload
```

- Store `upload-keystore.jks` and both passwords in two safe places. Losing it means asking Google to reset the upload key.
- Enable **Play App Signing** on first upload; this key is only the upload key.
- Never commit it (`*.jks`, `key.properties`).

### 2. Add GitHub secrets
Settings > Secrets and variables > Actions > New repository secret:

| Secret | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | output of `base64 -w0 upload-keystore.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | keystore password |
| `ANDROID_KEY_ALIAS` | `upload` (or your alias) |
| `ANDROID_KEY_PASSWORD` | key password |

If any of the four is missing, the workflow builds a debug-signed APK for internal testing only (not store-ready, no AAB).

### 3. Run the workflow
Actions > **mobile-release** > Run workflow. Inputs:
- `api_base_url`: backend URL, **https only** (passed as `--dart-define=FF_API_BASE_URL`; mock mode is turned off with `FF_MOCK=false`).
- `build_name` (e.g. `0.1.0`) and `build_number` (integer, increasing). Leave empty to use `pubspec.yaml`.
- `build_aab`: also build the Play bundle.

Artifacts: `factory-finder-apk-*` and `factory-finder-aab-signed` (kept 30 days). Keystore files are deleted from the runner after the build.

### 4. Versioning rules
- `version: X.Y.Z+N` in `apps/mobile/pubspec.yaml`: `X.Y.Z` is the user-visible SemVer name, `N` is the versionCode.
- `N` must increase on every Play upload and is never reused.
- Bump Y for features, Z for fixes, X for major changes.
- Workflow inputs override pubspec; pick one source and stick to it.
- Tag every published release (orchestrator's job, not agents').

### 5. Google Play checklist
- [ ] **Privacy policy URL**, public and live (from `docs/PRIVACY_POLICY.draft.md` after legal review and filling the [ ] fields).
- [ ] **Account/data deletion URL** on the web plus an in-app delete-account screen (does not exist yet; required before submission).
- [ ] **Data safety form** (must match what the app actually collects; see `docs/STORE_LISTING.md` §6):
  - Collected: email, name/company/phone (optional), user ID, photos (optional, EXIF/location stripped), verification documents (optional), messages, user-generated content (listings/requests/offers/reviews), financial metadata only (no card numbers), push device token if enabled.
  - Not collected: location, analytics, in-app crash logs.
  - Not shared with third parties, not sold, not used for ads (FCM only as processor, if enabled).
  - Encrypted in transit: yes (HTTPS). Deletion request: supported.
  - Re-review when adding any SDK (Firebase etc.) or enabling payments.
- [ ] **Content rating (IARC):** user-generated content and chat; no violence, gambling or mature content; no precise location. Minimum age 18 (business use). Answer honestly.
- [ ] **App icon** 512x512 PNG, and replace the default Flutter launcher icon in the bundle.
- [ ] **Feature graphic** 1024x500.
- [ ] **Screenshots** (min 2, up to 8; Arabic RTL first, then English): Discover feed, search results, listing detail with trust factors, supplier page with verification, landed-cost calculator, requests and offers, chat, shipment tracking, assistant, settings. Use demo data; no logos you do not own.
- [ ] Category (Business), description, keywords (`docs/STORE_LISTING.md`).
- [ ] Demo account for reviewers; explain mock vs live server; note customs and cost figures are estimates.
- [ ] Declared permissions: Internet, Camera, photo read (optional); justify them in the form.
- [ ] Internal then closed testing before production (new personal developer accounts have closed-testing requirements; check current rules).
