# إعداد الإشعارات (Firebase / FCM)

## العربية

الوضع الافتراضي: `NoopPushTokenSource` (لا إشعارات دفع). التطبيق يُبنى ويعمل بدون Firebase. اتبع الخطوات لتفعيلها.

### 1. إنشاء مشروع Firebase
console.firebase.google.com ← Add project ← اسم المشروع ← (التحليلات اختيارية؛ لا تفعّلها، فالتطبيق لا يجمع تحليلات انظر `docs/RELEASE.md` §5).

### 2. إضافة تطبيق أندرويد
Project settings ← Add app ← Android. معرّف الحزمة (Application ID):

`com.factoryfinder.factory_finder`

(مأخوذ من `--org com.factoryfinder --project-name factory_finder` في `apps/mobile/tool/ci_prepare_platforms.sh`؛ تأكد منه في `android/app/src/main/AndroidManifest.xml` بعد التوليد). أضف بصمة SHA-1 لمفتاح الرفع إن طُلب.

### 3. تنزيل google-services.json
نزّل الملف. **لا ترفعه إلى Git** (المستودع عام).

### 4. إضافة السر في GitHub
```bash
base64 -w0 google-services.json
```
Settings ← Secrets and variables ← Actions ← سر باسم `GOOGLE_SERVICES_JSON_BASE64` والقيمة ناتج الأمر.
عند وجوده يفك workflow `mobile-release` الملف إلى `android/app/google-services.json` ويطبّق إضافة Gradle (`tool/ci_enable_firebase.sh`) ثم يحذف الملف بعد البناء. إن غاب السر لا يتغير شيء.

### 5. إضافة الحزم (في `apps/mobile`)
```bash
flutter pub add firebase_core firebase_messaging
```
(iOS: يلزم مفتاح APNs في Firebase وقدرة Push Notifications في Xcode؛ خارج نطاق هذا الدليل.)

### 6. التحويل من Noop إلى Firebase
1. غيّر اسم الملف:
   `apps/mobile/lib/features/notify_prefs/firebase_push_token_source.dart.template` ← `firebase_push_token_source.dart`
2. في `push_registration.dart` (أو عبر override في `ProviderScope`) استبدل المصدر:
```dart
// main.dart
ProviderScope(
  overrides: [pushTokenSourceProvider.overrideWithValue(FirebasePushTokenSource())],
  child: const App(),
)
```
مع `import 'package:factory_finder/features/notify_prefs/firebase_push_token_source.dart';`.
3. أندرويد 13+: أضف `<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>` للـ manifest.
4. للبناء المحلي: ضع `google-services.json` في `android/app/` ثم `bash apps/mobile/tool/ci_enable_firebase.sh`.

لا تُغيّر الاختبارات: تستخدم مصادر وهمية. لا تُدرج الملف الحقيقي في المستودع قبل الخطوة 5 وإلا يفشل `flutter analyze`.

### 7. بعد التفعيل
حدّث نموذج أمان البيانات في Play (FCM مزود معالجة، رمز الجهاز يُجمع) وسياسة الخصوصية.

---

## English

Default is `NoopPushTokenSource`; the app builds without Firebase. To enable push:

1. Create a Firebase project (analytics off).
2. Add an Android app with Application ID `com.factoryfinder.factory_finder` (from `ci_prepare_platforms.sh`; verify in the generated manifest).
3. Download `google-services.json` (never commit it).
4. Add GitHub secret `GOOGLE_SERVICES_JSON_BASE64` (`base64 -w0 google-services.json`). When present, `mobile-release` decodes it, runs `tool/ci_enable_firebase.sh` (applies the Google Services Gradle plugin) and deletes the file afterwards.
5. `flutter pub add firebase_core firebase_messaging` in `apps/mobile`.
6. Rename `firebase_push_token_source.dart.template` to `.dart` and override `pushTokenSourceProvider` with `FirebasePushTokenSource()` in the root `ProviderScope`. Add `POST_NOTIFICATIONS` to the manifest for Android 13+.
7. Update the Play Data safety form and privacy policy.
