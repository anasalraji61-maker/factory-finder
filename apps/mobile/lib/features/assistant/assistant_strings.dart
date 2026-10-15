import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/assistant/assistant_models.dart';

final Map<String, Map<String, String>> assistantStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'assistant.title': ('المساعد الذكي', 'Smart assistant'),
  'assistant.hint': ('اسأل عن منتج أو شحنة أو صفقة…', 'Ask about a product, shipment or deal…'),
  'assistant.send': ('إرسال', 'Send'),
  'assistant.empty_title': ('كيف أساعدك؟', 'How can I help?'),
  'assistant.empty_msg': (
    'اسأل عن حالة شحنة، صفقة، مقارنة عرضين، أو رمز جمركي.',
    'Ask about a shipment, a deal, comparing two listings, or an HS code.',
  ),
  'assistant.thinking': ('جارٍ التفكير…', 'Thinking…'),
  'assistant.error': ('تعذّر الحصول على إجابة. حاول مرة أخرى.', 'Could not get an answer. Please try again.'),
  'assistant.quota': (
    'وصلت إلى الحد اليومي لأسئلة المساعد. حاول مجدداً بعد {wait}.',
    'You have reached the assistant daily limit. Try again in {wait}.',
  ),
  'assistant.quota_later': ('وقت لاحق', 'a while'),
  'assistant.wait_minutes': ('{n} دقيقة', '{n} min'),
  'assistant.wait_hours': ('{n} ساعة', '{n} h'),
  'assistant.filtered': (
    'تمت إزالة نص مشبوه من بيانات خارجية في هذه الإجابة.',
    'Some suspicious text from third-party data was removed from this answer.',
  ),
  'assistant.open_shipment': ('فتح الشحنة', 'Open shipment'),
  'assistant.open_listing': ('عرض المنتج {n}', 'View listing {n}'),
  'assistant.open_request_form': ('فتح نموذج الطلب', 'Open request form'),
  'assistant.open_deals': ('فتح الصفقات', 'Open deals'),
  'assistant.sign_in': ('تسجيل الدخول', 'Sign in'),
  'assistant.empty_value': ('—', '—'),
  'logistics.tool.assistant': ('المساعد الذكي', 'Smart assistant'),
};

/// User-facing text for a failed query, in [lang] ('ar' or 'en'). 429 gets the
/// quota message with the Retry-After wait when known.
String assistantErrorText(Object e, String lang) {
  if (isQuotaError(e)) {
    final secs = e is ApiException ? e.retryAfterSeconds : null;
    String wait;
    if (secs == null || secs <= 0) {
      wait = AppStrings.lookup(lang, 'assistant.quota_later');
    } else if (secs < 3600) {
      wait = AppStrings.lookup(lang, 'assistant.wait_minutes', {'n': '${(secs / 60).ceil()}'});
    } else {
      wait = AppStrings.lookup(lang, 'assistant.wait_hours', {'n': '${(secs / 3600).ceil()}'});
    }
    return AppStrings.lookup(lang, 'assistant.quota', {'wait': wait});
  }
  return AppStrings.lookup(lang, 'assistant.error');
}
