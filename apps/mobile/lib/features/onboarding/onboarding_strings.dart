import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/onboarding/intro_strings.dart';

final Map<String, Map<String, String>> onboardingStrings =
    mergeStringTables([bilingual(_pairs), introStrings]);

const Map<String, (String, String)> _pairs = {
  'onb.skip': ('تخطّي', 'Skip'),
  'onb.next': ('التالي', 'Next'),
  'onb.back': ('رجوع', 'Back'),
  'onb.start': ('ابدأ', 'Get started'),
  'onb.p1.title': ('مرحباً بك في مُوَرِّد', 'Welcome to Factory Finder'),
  'onb.p1.body': ('ابحث عن المنتجات والمواد الأولية وخطوط الإنتاج، تحقق من مصداقية المورد، واحسب الكلفة الكاملة لحد بابك.', 'Search products, raw materials and production lines, check supplier trust, and see the full cost to your door.'),
  'onb.p1.point1': ('موردون من الصين وغيرها', 'Suppliers from China and beyond'),
  'onb.p1.point2': ('تقييم ثقة لكل مورد', 'A trust score for every supplier'),
  'onb.p1.point3': ('كلفة شحن وجمارك بعملتك', 'Shipping and duties in your currency'),
  'onb.p2.title': ('خصّص تجربتك', 'Make it yours'),
  'onb.language': ('اللغة', 'Language'),
  'onb.currency': ('عملة العرض', 'Display currency'),
  'onb.destination': ('وجهة التسليم الافتراضية', 'Default destination'),
  'onb.p3.title': ('كيف ستستخدم التطبيق؟', 'How will you use the app?'),
  'onb.role.buyer': ('مشتري', 'Buyer'),
  'onb.role.buyer_desc': ('أبحث عن موردين وأحسب الكلفة', 'I look for suppliers and compute costs'),
  'onb.role.supplier': ('مورّد', 'Supplier'),
  'onb.role.supplier_desc': ('أعرض منتجاتي وأستقبل الطلبات', 'I list products and receive requests'),
};
