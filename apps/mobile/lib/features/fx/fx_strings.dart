import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> fxStrings = bilingual({
  'fx.title': ('أسعار الصرف', 'Exchange rates'),
  'fx.base': ('العملة الأساسية', 'Base currency'),
  'fx.rates_title': ('الأسعار مقابل {base}', 'Rates per 1 {base}'),
  'fx.converter': ('محوّل العملات', 'Currency converter'),
  'fx.amount': ('المبلغ', 'Amount'),
  'fx.from': ('من', 'From'),
  'fx.to': ('إلى', 'To'),
  'fx.swap': ('تبديل', 'Swap'),
  'fx.result': ('النتيجة', 'Result'),
  'fx.rate_line': ('1 {from} = {rate} {to}', '1 {from} = {rate} {to}'),
  'fx.as_of': ('بتاريخ {time}', 'As of {time}'),
  'fx.source': ('المصدر: {source}', 'Source: {source}'),
  'fx.invalid_amount': ('أدخل مبلغاً صحيحاً', 'Enter a valid amount'),
  'fx.empty_title': ('لا توجد أسعار', 'No rates available'),
  'fx.empty_msg': ('اسحب للتحديث وحاول مجدداً.', 'Pull to refresh and try again.'),
});
