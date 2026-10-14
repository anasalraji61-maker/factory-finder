import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> trustStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'trust.confidence': ('مستوى الثقة بالتقييم', 'Score confidence'),
  'trust.confidence_value': ('{n}%', '{n}%'),
  'trust.confidence_low': ('قليل', 'Low'),
  'trust.confidence_mid': ('متوسط', 'Medium'),
  'trust.confidence_high': ('مرتفع', 'High'),
  'trust.confidence_hint': (
    'يوضح هذا المقياس مقدار البيانات التي يستند إليها التقييم. قلة الأدلة لا تعني أن المورد سيئ، بل أن المعلومات المتاحة عنه أقل.',
    'This shows how much evidence backs the score. Low evidence does not mean a bad supplier, only that less is known about them.'
  ),
  'trust.gaps_title': ('معلومات ناقصة', 'Missing information'),
  'trust.gaps_hint': (
    'توفّر هذه المعلومات يرفع مستوى الثقة بالتقييم.',
    'Providing this information would raise confidence in the score.'
  ),
  'trust.flags_title': ('تنبيهات', 'Flags'),
  'trust.flag.sanctions_hit': ('ورد في قوائم العقوبات', 'Sanctions list match'),
  'trust.flag.blocked_flag': ('محظور', 'Blocked'),
  'trust.flag.price_anomaly': ('سعر غير معتاد', 'Unusual pricing'),
  'trust.flag.certification_expired': ('شهادة منتهية', 'Certification expired'),
  'trust.flag.certification_expiring': ('شهادة قاربت على الانتهاء', 'Certification expiring'),
  'trust.history_title': ('تطوّر التقييم', 'Score over time'),
  'trust.history_empty': ('لا يوجد سجل كافٍ بعد', 'Not enough history yet'),
  'trust.history_loading': ('جارٍ تحميل السجل…', 'Loading history…'),
  'trust.history_failed': ('تعذر تحميل السجل', 'Could not load history'),
  'trust.report.open': ('الإبلاغ عن مشكلة', 'Report a concern'),
  'trust.report.title': ('الإبلاغ عن مشكلة مع المورد', 'Report a concern about this supplier'),
  'trust.report.note': (
    'تُراجَع البلاغات يدوياً ولا تؤثر على التقييم إلا بعد قبولها.',
    'Reports are reviewed by a moderator and affect the score only once accepted.'
  ),
  'trust.report.type': ('نوع المشكلة', 'Type of concern'),
  'trust.report.type_hint': ('اختر النوع', 'Choose a type'),
  'trust.report.text': ('التفاصيل', 'Details'),
  'trust.report.submit': ('إرسال البلاغ', 'Submit report'),
  'trust.report.err_type': ('اختر نوع المشكلة', 'Choose a type of concern'),
  'trust.report.err_text': ('اكتب وصفاً للمشكلة', 'Describe the concern'),
  'trust.report.err_long': ('النص أطول من 1000 حرف', 'Text is longer than 1000 characters'),
  'trust.report.success': ('تم استلام بلاغك وسيُراجَع قريباً. شكراً لك.', 'Your report was received and will be reviewed. Thank you.'),
  'trust.report.rate_limited': ('أرسلت بلاغات كثيرة. حاول مجدداً بعد قليل.', 'You have sent too many reports. Please try again later.'),
  'trust.report.login': ('سجّل الدخول لإرسال بلاغ', 'Sign in to submit a report'),
  'trust.report.failed': ('تعذر إرسال البلاغ', 'Could not send the report'),
  'trust.report.close': ('إغلاق', 'Close'),
  'trust.report_type.fraud': ('احتيال', 'Fraud'),
  'trust.report_type.counterfeit': ('منتجات مقلّدة', 'Counterfeit goods'),
  'trust.report_type.non_delivery': ('عدم التسليم', 'Non-delivery'),
  'trust.report_type.quality': ('مشكلة جودة', 'Quality problem'),
  'trust.report_type.misrepresentation': ('تضليل في الوصف', 'Misrepresentation'),
  'trust.report_type.unsafe_product': ('منتج غير آمن', 'Unsafe product'),
  'trust.report_type.other': ('أخرى', 'Other'),
};
