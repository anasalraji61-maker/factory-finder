import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> legalStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'legal.tile.privacy': ('سياسة الخصوصية', 'Privacy Policy'),
  'legal.tile.privacy_sub': ('كيف نجمع بياناتك ونستخدمها', 'How we collect and use your data'),
  'legal.tile.terms': ('شروط الخدمة', 'Terms of Service'),
  'legal.tile.terms_sub': ('القواعد التي تحكم استخدام التطبيق', 'The rules for using the app'),
  'legal.draft': ('مسودة. ليست استشارة قانونية وتخضع لمراجعة محامٍ قبل النشر.', 'DRAFT. Not legal advice; pending lawyer review before publication.'),
  'legal.summary_note': ('ملخص للنقاط الرئيسية فقط. النص الكامل في الرابط أدناه.', 'A summary of the key points only. The full text is at the link below.'),
  'legal.privacy.title': ('سياسة الخصوصية', 'Privacy Policy'),
  'legal.privacy.p1': ('نخزّن بيانات حسابك (البريد والاسم والشركة والهاتف) وما تنشره من إعلانات وطلبات ورسائل. كلمات المرور تُخزَّن مجزّأة فقط.', 'We store your account data (email, name, company, phone) and what you post: listings, requests and messages. Passwords are stored hashed only.'),
  'legal.privacy.p2': ('الصور المرفوعة تُزال بياناتها الوصفية بما فيها الموقع.', 'Uploaded images have their metadata, including location, removed.'),
  'legal.privacy.p3': ('لا نبيع بياناتك. نشاركها فقط مع مزوّدي الخدمة اللازمين لتشغيل التطبيق.', 'We do not sell your data. We share it only with the service providers needed to run the app.'),
  'legal.privacy.p4': ('يمكنك تصدير بياناتك وحذف حسابك في أي وقت من الإعدادات > الخصوصية والبيانات.', 'You can export your data and delete your account at any time in Settings > Privacy & data.'),
  'legal.privacy.p5': ('سجلّ المدفوعات والصفقات يبقى لأغراض التدقيق والالتزام القانوني بدون ربطه بهويتك بعد الحذف.', 'The payments ledger and deals are kept for audit and legal reasons, unlinked from your identity after deletion.'),
  'legal.terms.title': ('شروط الخدمة', 'Terms of Service'),
  'legal.terms.p1': ('مُوَرِّد منصة وساطة تربط المشترين بالموردين وتقدّر كلفة الاستيراد. التقديرات استرشادية وليست عرض سعر ملزماً.', 'Factory Finder is an intermediary platform that connects buyers with suppliers and estimates import costs. Estimates are indicative, not binding quotes.'),
  'legal.terms.p2': ('أنت مسؤول عن صحة ما تنشره وعن حفظ بيانات دخولك.', 'You are responsible for the accuracy of what you post and for keeping your credentials safe.'),
  'legal.terms.p3': ('يُمنع نشر سلع محظورة أو محتوى مضلل أو الالتفاف على المنصة بروابط وأرقام هاتف.', 'Prohibited goods, misleading content, and bypassing the platform with links or phone numbers are not allowed.'),
  'legal.terms.p4': ('قد نوقف الحسابات المخالفة. قد نتقاضى عمولة على الصفقات التي تتم عبر المنصة.', 'We may suspend accounts that break these terms. We may charge a commission on deals made through the platform.'),
  'legal.terms.p5': ('نتحقق من الموردين بحسب المتاح، لكننا لا نضمن جودة السلع أو التزام الأطراف.', 'We vet suppliers as far as we can, but we do not guarantee goods quality or that parties will perform.'),
  'legal.url.label': ('الرابط الكامل', 'Full text link'),
  'legal.url.unavailable': ('الرابط غير متاح بعد.', 'The link is not available yet.'),
  'legal.url.copy': ('نسخ الرابط', 'Copy link'),
  'legal.url.copied': ('تم نسخ الرابط', 'Link copied'),
};
