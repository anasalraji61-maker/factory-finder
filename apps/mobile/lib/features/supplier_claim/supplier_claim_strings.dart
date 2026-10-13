import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> supplierClaimStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'claim.tile_title': ('حساب المورّد', 'Supplier account'),
  'claim.not_linked': ('غير مرتبط', 'Not linked'),
  'claim.title': ('ربط حساب المورّد', 'Claim my supplier account'),
  'claim.intro': (
    'أدخل معرّف المورّد في الدليل لربطه بحسابك.',
    'Enter your catalog supplier id to link it to your account.',
  ),
  'claim.field': ('معرّف المورّد', 'Supplier id'),
  'claim.hint': ('sup_...', 'sup_...'),
  'claim.current': ('المورّد المرتبط حالياً: {id}', 'Currently linked: {id}'),
  'claim.status.pending': (
    'قيد المراجعة: طلب الربط بانتظار موافقة الإدارة',
    'Under review: your claim is awaiting admin approval',
  ),
  'claim.status.verified': ('تم التحقق', 'Verified'),
  'claim.pending_short': ('{id} (قيد المراجعة)', '{id} (under review)'),
  'claim.claim': ('ربط', 'Claim'),
  'claim.release': ('إلغاء الربط', 'Release'),
  'claim.err.format': (
    'المعرّف يجب أن يبدأ بـ sup_ ويحتوي حروفاً وأرقاماً وشرطة سفلية فقط',
    'Id must start with sup_ and contain only letters, digits and underscores',
  ),
  'claim.err.taken': (
    'هذا المورّد مرتبط بحساب آخر بالفعل.',
    'This supplier is already claimed by another account.',
  ),
  'claim.err.generic': ('تعذّر إكمال الطلب. حاول مرة أخرى.', 'Could not complete the request. Please try again.'),
  'claim.ok_claimed': ('تم إرسال الطلب للمراجعة', 'Claim submitted for review'),
  'claim.ok_released': ('تم إلغاء الربط', 'Supplier account released'),
  'claim.signin': ('سجّل الدخول أولاً لربط حساب المورّد.', 'Sign in first to claim a supplier account.'),
};
