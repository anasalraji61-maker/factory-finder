import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> introStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'intro.skip': ('تخطّي', 'Skip'),
  'intro.next': ('التالي', 'Next'),
  'intro.start': ('ابدأ الآن', 'Get started'),
  'intro.lang_toggle': ('English', 'العربية'),
  'intro.lang_toggle_label': ('تغيير اللغة إلى الإنجليزية', 'Switch language to Arabic'),
  'intro.page_of': ('الصفحة {n} من {total}', 'Page {n} of {total}'),
  'intro.p1.title': ('ابحث عن أي منتج أو مادة أو خط إنتاج', 'Search any product, material or production line'),
  'intro.p1.body': ('منتجات جديدة ومستعملة من موردين حول العالم، بداية من الصين.', 'New and used items from suppliers worldwide, starting with China.'),
  'intro.p2.title': ('اعرف الكلفة الكاملة لباب بيتك', 'Know the full cost to your door'),
  'intro.p2.body': ('من المصنع حتى مدينتك: النقل الداخلي والشحن والجمارك والتوصيل بعملتك.', 'From factory to your city: inland haul, freight, duties and delivery in your currency.'),
  'intro.p2.estimate': ('تقدير تقريبي', 'Estimate'),
  'intro.p2.estimate_note': ('الأرقام تقديرية ضمن نطاق، وقد تختلف الكلفة الفعلية.', 'Figures are estimates shown as a range; actual costs may differ.'),
  'intro.p2.step1': ('نقل داخلي من المصنع', 'Inland haul from the factory'),
  'intro.p2.step2': ('شحن بحري أو جوي أو بري', 'Sea, air or land freight'),
  'intro.p2.step3': ('جمارك وضرائب', 'Duties and taxes'),
  'intro.p2.step4': ('توصيل لباب بيتك', 'Delivery to your door'),
  'intro.p3.title': ('تحقق من المورد وتابع شحنتك', 'Verify the supplier and track your shipment'),
  'intro.p3.body': ('تقييم ثقة لكل مورد، وتتبع الحاوية أو الشحنة الجوية خطوة بخطوة.', 'A trust score for every supplier, and step-by-step container or air shipment tracking.'),
  'intro.replay': ('إعادة عرض المقدمة', 'Replay intro'),
  'intro.replay_sub': ('شاهد جولة التعريف بالتطبيق مرة أخرى', 'See the app tour again'),
  'intro.about': ('حول التطبيق', 'About'),
};
