import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> authStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'auth.login': ('تسجيل الدخول', 'Sign in'),
  'auth.register': ('إنشاء حساب', 'Create account'),
  'auth.logout': ('تسجيل الخروج', 'Sign out'),
  'auth.name': ('الاسم', 'Name'),
  'auth.email': ('البريد الإلكتروني', 'Email'),
  'auth.phone': ('رقم الهاتف (اختياري)', 'Phone (optional)'),
  'auth.password': ('كلمة المرور', 'Password'),
  'auth.have_account': ('لدي حساب بالفعل', 'I already have an account'),
  'auth.no_account': ('ليس لدي حساب', 'I do not have an account'),
  'auth.err.name': ('الاسم مطلوب', 'Name is required'),
  'auth.err.email': ('أدخل بريداً إلكترونياً صحيحاً', 'Enter a valid email'),
  'auth.err.password': ('كلمة المرور 8 أحرف على الأقل', 'Password needs at least 8 characters'),
  'auth.welcome': ('مرحباً {name}', 'Welcome {name}'),
  'auth.guest': ('زائر', 'Guest'),
  'auth.guest_hint': ('سجّل الدخول لنشر الطلبات وقبول العروض.', 'Sign in to post requests and accept offers.'),
  'auth.mock_note': ('وضع تجريبي: أي بيانات تعمل.', 'Demo mode: any credentials work.'),
  'auth.session_required': ('سجّل الدخول أولاً', 'Please sign in first'),
  'profile.server_url': ('عنوان الخادم', 'Server URL'),
  'profile.server_hint': ('يُستخدم عند تشغيل التطبيق مع الخادم الحقيقي (FF_MOCK=false).', 'Used when the app runs against the real backend (FF_MOCK=false).'),
  'profile.server_mock': ('التطبيق في الوضع التجريبي حالياً.', 'The app is currently in demo mode.'),
};
