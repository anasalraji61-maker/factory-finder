import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> recoStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'reco.price_history': ('سجل السعر', 'Price history'),
  'reco.range_days': ('{n} يوماً', '{n} days'),
  'reco.min': ('الأدنى', 'Lowest'),
  'reco.max': ('الأعلى', 'Highest'),
  'reco.avg': ('المتوسط', 'Average'),
  'reco.trend.up': ('ارتفاع', 'Rising'),
  'reco.trend.down': ('انخفاض', 'Falling'),
  'reco.trend.flat': ('مستقر', 'Stable'),
  'reco.synthetic': (
    'بيانات تقديرية توضيحية، وليست أسعاراً مسجلة فعلياً.',
    'Estimated, illustrative data, not recorded prices.'
  ),
  'reco.insufficient': (
    'لا توجد بيانات كافية بعد لعرض اتجاه السعر.',
    'Not enough price data yet to show a trend.'
  ),
  'reco.at_low': ('السعر الحالي عند أدنى مستوى في هذه الفترة.', 'The current price is at its lowest in this period.'),
  'reco.at_high': ('السعر الحالي عند أعلى مستوى في هذه الفترة.', 'The current price is at its highest in this period.'),
  'reco.alert_suggested': ('نبّهني عند السعر المقترح', 'Alert me at the suggested price'),
  'reco.suggested': ('السعر المقترح: {price}', 'Suggested price: {price}'),
  'reco.chart_a11y': (
    'مخطط سعر {days} يوماً من {from} إلى {to}، الاتجاه: {trend}',
    'Price chart for {days} days from {from} to {to}, trend: {trend}'
  ),
  'reco.load_failed': ('تعذر تحميل سجل السعر', 'Could not load the price history'),
  'reco.similar': ('منتجات مشابهة', 'Similar listings'),
  'reco.title': ('موصى به لك', 'Recommended for you'),
  'reco.recent_title': ('المشاهدات الأخيرة', 'Recently viewed'),
  'reco.recent_hint': (
    'نحفظ آخر ما شاهدته على جهازك فقط لاقتراح منتجات مشابهة. لا يُرسل أي تتبع إلى الخادم.',
    'Your last viewed listings stay on this device and are only used to suggest similar ones. Nothing is tracked on the server.'
  ),
  'reco.recent_clear': ('مسح المشاهدات الأخيرة', 'Clear recently viewed'),
  'reco.recent_cleared': ('تم مسح المشاهدات الأخيرة', 'Recently viewed cleared'),
};
