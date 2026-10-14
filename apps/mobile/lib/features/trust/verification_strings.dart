import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> verificationStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'ver.tile': ('توثيق النشاط التجاري', 'Business verification'),
  'ver.tile_sub': ('أرسل مستنداتك لرفع مستوى الثقة', 'Submit documents to raise buyer trust'),
  'ver.title': ('توثيق النشاط التجاري', 'Business verification'),
  'ver.intro': (
    'أرسل مستندات نشاطك التجاري لتظهر شارة التوثيق للمشترين. تُراجَع المستندات يدوياً، ولا يُعرض رقم المستند ولا ملفاته للعموم.',
    'Submit your business documents to show a verification badge to buyers. Documents are reviewed manually; the number and files are never shown publicly.'
  ),
  'ver.level_title': ('مستوى التوثيق الحالي', 'Current verification level'),
  'ver.level.none': ('غير موثّق', 'Not verified'),
  'ver.level.basic': ('توثيق أساسي', 'Basic verification'),
  'ver.level.documented': ('موثّق بالمستندات', 'Documented'),
  'ver.level.audited': ('موثّق ومدقَّق', 'Audited'),
  'ver.badge.basic': ('نشاط موثّق: أساسي', 'Verified business: basic'),
  'ver.badge.documented': ('نشاط موثّق بالمستندات', 'Verified business: documented'),
  'ver.badge.audited': ('نشاط موثّق ومدقَّق', 'Verified business: audited'),
  'ver.docs_title': ('مستنداتي', 'My documents'),
  'ver.empty': ('لم ترسل أي مستند بعد.', 'You have not submitted any document yet.'),
  'ver.add': ('إضافة مستند', 'Add a document'),
  'ver.type.business_license': ('رخصة تجارية', 'Business licence'),
  'ver.type.company_registry_reference': ('رقم السجل التجاري', 'Company registry reference'),
  'ver.type.bank_reference': ('مرجع مصرفي', 'Bank reference'),
  'ver.type.export_license': ('إجازة تصدير', 'Export licence'),
  'ver.type.factory_photos': ('صور المصنع', 'Factory photos'),
  'ver.type.iso_certificate': ('شهادة آيزو', 'ISO certificate'),
  'ver.type.other_certificate': ('شهادة أخرى', 'Other certificate'),
  'ver.status.pending': ('قيد المراجعة', 'Pending'),
  'ver.status.approved': ('مقبول', 'Approved'),
  'ver.status.rejected': ('مرفوض', 'Rejected'),
  'ver.status.withdrawn': ('مسحوب', 'Withdrawn'),
  'ver.status.expired': ('منتهي الصلاحية', 'Expired'),
  'ver.number': ('الرقم: {n}', 'Number: {n}'),
  'ver.country': ('بلد الإصدار: {c}', 'Issued in: {c}'),
  'ver.expires': ('ينتهي في {d}', 'Expires {d}'),
  'ver.files_n': ('{n} ملف', '{n} file(s)'),
  'ver.reason': ('سبب الرفض: {r}', 'Rejection reason: {r}'),
  'ver.withdraw': ('سحب', 'Withdraw'),
  'ver.withdraw_title': ('سحب المستند؟', 'Withdraw this document?'),
  'ver.withdraw_msg': (
    'لن يُحتسب المستند في مستوى التوثيق بعد سحبه.',
    'The document will no longer count towards your verification level.'
  ),
  'ver.withdraw_ok': ('تم سحب المستند', 'Document withdrawn'),
  'ver.cancel': ('إلغاء', 'Cancel'),
  'ver.sheet_title': ('إرسال مستند', 'Submit a document'),
  'ver.f.type': ('نوع المستند', 'Document type'),
  'ver.f.country': ('بلد الإصدار (رمزان)', 'Issuing country (2 letters)'),
  'ver.f.country_hint': ('مثال: IQ', 'e.g. IQ'),
  'ver.f.number': ('رقم المستند', 'Document number'),
  'ver.f.number_none': ('هذا النوع لا يحتاج رقماً.', 'This type needs no number.'),
  'ver.f.expiry': ('تاريخ الانتهاء (اختياري)', 'Expiry date (optional)'),
  'ver.f.expiry_hint': ('YYYY-MM-DD', 'YYYY-MM-DD'),
  'ver.f.pick_date': ('اختيار تاريخ', 'Pick a date'),
  'ver.f.consent': (
    'أوافق على أن تراجع المنصة هذه المستندات للتحقق من نشاطي التجاري.',
    'I agree that the platform may review these documents to verify my business.'
  ),
  'ver.f.files': ('صور المستند', 'Document images'),
  'ver.f.files_count': ('{n} من {max} صور', '{n} of {max} images'),
  'ver.f.gallery': ('من المعرض', 'From gallery'),
  'ver.f.camera': ('الكاميرا', 'Camera'),
  'ver.f.remove': ('حذف الصورة', 'Remove image'),
  'ver.f.uploading': ('جارٍ رفع الصورة…', 'Uploading image…'),
  'ver.submit': ('إرسال للمراجعة', 'Submit for review'),
  'ver.submit_ok': ('تم إرسال المستند للمراجعة', 'Document submitted for review'),
  'ver.signin': ('سجّل الدخول أولاً.', 'Sign in first.'),
  'ver.gate_title': ('اربط حساب المورّد أولاً', 'Link your supplier account first'),
  'ver.gate_msg': (
    'يلزم حساب مورّد موثَّق الربط لإرسال مستندات التوثيق.',
    'A verified supplier account link is required to submit verification documents.'
  ),
  'ver.gate_button': ('ربط حساب المورّد', 'Go to supplier account'),
  'ver.err.type': ('اختر نوع المستند', 'Choose a document type'),
  'ver.err.country': ('أدخل رمز البلد من حرفين (مثل IQ)', 'Enter a 2-letter country code (e.g. IQ)'),
  'ver.err.number': ('رقم المستند مطلوب (من 4 إلى 64 حرفاً)', 'A document number is required (4 to 64 characters)'),
  'ver.err.number_not_allowed': ('هذا النوع من المستندات لا يحمل رقماً.', 'This document type carries no number.'),
  'ver.err.expiry_format': ('استخدم الصيغة YYYY-MM-DD', 'Use the format YYYY-MM-DD'),
  'ver.err.expiry_past': ('المستند منتهي الصلاحية بالفعل', 'The document is already expired'),
  'ver.err.files': ('أضف من صورة إلى 10 صور', 'Add between 1 and 10 images'),
  'ver.err.file_url': (
    'ملف غير مقبول. احذف الصور وارفعها من جديد من داخل التطبيق (لا تُقبل روابط الصور العامة).',
    'File not accepted. Remove the images and upload them again from the app (public image links are not accepted).'
  ),
  'ver.thumb_failed': ('تعذّر عرض الصورة', 'Image unavailable'),
  'ver.thumb_label': ('صورة المستند {n}', 'Document image {n}'),
  'ver.err.consent': ('الموافقة على المراجعة مطلوبة', 'Consent to the review is required'),
  'ver.err.supplier_required': (
    'يلزم حساب مورّد موثَّق لهذا الإجراء.',
    'A verified supplier account is required for this action.'
  ),
  'ver.err.duplicate': ('سبق إرسال هذا المستند.', 'This document was already submitted.'),
  'ver.err.limit': ('وصلت إلى الحد الأقصى من المستندات النشطة.', 'You reached the maximum number of active documents.'),
  'ver.err.type_limit': (
    'وصلت إلى الحد الأقصى من المستندات النشطة لهذا النوع.',
    'You reached the maximum number of active documents of this type.'
  ),
  'ver.err.transition': ('لا يمكن سحب هذا المستند في حالته الحالية.', 'This document cannot be withdrawn in its current state.'),
  'ver.err.not_found': ('المستند غير موجود.', 'Document not found.'),
  'ver.err.capacity': ('الخدمة مشغولة حالياً. حاول لاحقاً.', 'The service is busy right now. Try again later.'),
  'ver.err.rate_limited': ('أرسلت مستندات كثيرة. حاول لاحقاً.', 'You submitted too many documents. Try again later.'),
  'ver.err.rate_limited_wait': (
    'أرسلت مستندات كثيرة. حاول بعد {n} دقيقة تقريباً.',
    'You submitted too many documents. Try again in about {n} minute(s).'
  ),
  'ver.err.network': ('تعذّر الاتصال بالخادم.', 'Could not reach the server.'),
  'ver.err.generic': ('تعذّر إكمال الطلب. حاول مرة أخرى.', 'Could not complete the request. Please try again.'),
};
