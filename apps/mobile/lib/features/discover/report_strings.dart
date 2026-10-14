import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> reportStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'report.action': ('إبلاغ عن المنتج', 'Report listing'),
  'report.title': ('الإبلاغ عن هذا المنتج', 'Report this listing'),
  'report.subtitle': ('اختر السبب الأقرب. تبقى هويتك سرية ولا تُعرض للمورّد.', 'Pick the closest reason. Your identity stays private and is never shown to the supplier.'),
  'report.reason.prohibited_item': ('منتج ممنوع', 'Prohibited item'),
  'report.reason.counterfeit': ('منتج مقلّد', 'Counterfeit'),
  'report.reason.scam_or_fraud': ('احتيال أو نصب', 'Scam or fraud'),
  'report.reason.misleading': ('معلومات مضللة', 'Misleading information'),
  'report.reason.contact_info_in_listing': ('بيانات اتصال داخل الإعلان', 'Contact details in the listing'),
  'report.reason.offensive': ('محتوى مسيء', 'Offensive content'),
  'report.reason.other': ('سبب آخر', 'Other'),
  'report.details': ('تفاصيل إضافية (اختياري)', 'More details (optional)'),
  'report.details_hint': ('لا تكتب أرقام هاتف أو روابط، فهي تُحذف تلقائياً.', 'Do not add phone numbers or links; they are removed automatically.'),
  'report.submit': ('إرسال البلاغ', 'Send report'),
  'report.cancel': ('إلغاء', 'Cancel'),
  'report.pick_reason': ('اختر سبب البلاغ', 'Choose a reason'),
  'report.done': ('تم استلام بلاغك. شكراً لمساعدتك.', 'Report received. Thank you for helping.'),
  'report.err.auth': ('سجّل الدخول للإبلاغ عن منتج.', 'Sign in to report a listing.'),
  'report.err.not_found': ('هذا المنتج لم يعد متاحاً.', 'This listing is no longer available.'),
  'report.err.own_listing': ('لا يمكنك الإبلاغ عن منتجك.', 'You cannot report your own listing.'),
  'report.err.invalid': ('بيانات البلاغ غير صالحة. راجع السبب والتفاصيل.', 'The report is not valid. Check the reason and details.'),
  'report.err.rate_limited': ('أرسلت بلاغات كثيرة. حاول لاحقاً.', 'You have sent many reports. Try again later.'),
  'report.err.rate_limited_wait': ('أرسلت بلاغات كثيرة. حاول بعد {n} دقيقة.', 'You have sent many reports. Try again in {n} min.'),
  'report.err.network': ('تعذّر الاتصال بالخادم. تحقق من الإنترنت.', 'Could not reach the server. Check your connection.'),
  'report.err.generic': ('تعذّر إرسال البلاغ. حاول مرة أخرى.', 'Could not send the report. Please try again.'),
};
