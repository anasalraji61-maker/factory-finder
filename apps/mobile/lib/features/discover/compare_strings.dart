import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> compareStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'compare.add': ('أضف للمقارنة', 'Add to compare'),
  'compare.remove': ('أزل من المقارنة', 'Remove from compare'),
  'compare.full': ('يمكنك مقارنة {n} منتجات كحد أقصى', 'You can compare up to {n} listings'),
  'compare.tray': ('المقارنة: {n} من {max}', 'Compare: {n} of {max}'),
  'compare.open': ('قارن', 'Compare'),
  'compare.clear': ('مسح المقارنة', 'Clear comparison'),
  'compare.title': ('مقارنة المنتجات', 'Compare listings'),
  'compare.empty_title': ('لا توجد منتجات للمقارنة', 'Nothing to compare'),
  'compare.empty_msg': ('اضغط على أيقونة المقارنة في بطاقة المنتج لإضافته.', 'Tap the compare icon on a listing card to add it.'),
  'compare.row.price': ('نطاق السعر', 'Price range'),
  'compare.row.moq': ('الحد الأدنى للطلب', 'MOQ'),
  'compare.row.condition': ('الحالة', 'Condition'),
  'compare.row.trust': ('ثقة المورد', 'Supplier trust'),
  'compare.row.lead': ('مدة التجهيز', 'Lead time'),
  'compare.row.origin': ('بلد المنشأ', 'Origin'),
  'compare.row.landed': ('الكلفة الواصلة (تقدير)', 'Landed cost (estimate)'),
  'compare.landed_dest': ('إلى: {city}', 'To: {city}'),
  'compare.landed_unit': ('≈ {price} للوحدة', '≈ {price} per unit'),
  'compare.landed_unavailable': ('غير متاح', 'Unavailable'),
  'compare.best_price': ('أفضل سعر', 'Best price'),
  'compare.best_landed': ('أفضل كلفة واصلة', 'Best landed cost'),
  'compare.most_trusted': ('الأكثر ثقة', 'Most trusted'),
  'compare.na': ('—', '—'),
  'compare.save_search': ('حفظ هذا البحث', 'Save this search'),
  'compare.search_saved': ('تم حفظ البحث وسنخبرك بالنتائج الجديدة', 'Search saved. We will tell you about new results.'),
  'compare.search_empty': ('أدخل كلمات بحث أو فلاتر أولاً', 'Enter keywords or filters first'),
};
