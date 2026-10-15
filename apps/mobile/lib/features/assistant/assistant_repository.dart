import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/assistant/assistant_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class AssistantRepository {
  AssistantRepository(this._api);

  final ApiClient _api;

  /// Asks the assistant. [lang] is 'ar' or 'en'. A 429 surfaces as an
  /// [ApiException] (see isQuotaError) with Retry-After in retryAfterSeconds.
  Future<AssistantAnswer> ask(String text, {String lang = 'ar', Location? destination}) async {
    if (_api.isMock) {
      await mockDelay(300);
      return mockAssistantAnswer(text, lang: lang);
    }
    final json = await _api.post('/v1/assistant/query', body: {
      'text': text,
      'locale': lang == 'en' ? 'en' : 'ar',
      if (destination != null) 'destination': destination.toJson(),
    });
    return AssistantAnswer.fromJson(Map<String, dynamic>.from(json as Map));
  }
}

final assistantRepositoryProvider = Provider<AssistantRepository>(
  (ref) => AssistantRepository(ref.watch(apiClientProvider)),
);

Map<String, dynamic> _row(String key, String en, String ar, String vEn, [String? vAr]) =>
    {'key': key, 'label': en, 'label_ar': ar, 'value': vEn, 'value_ar': vAr ?? vEn};

/// Deterministic sample answers (mock mode / demos), keyed by simple keywords.
AssistantAnswer mockAssistantAnswer(String text, {String lang = 'ar'}) {
  final q = text.toLowerCase();
  final ar = lang == 'ar';
  Map<String, dynamic> body;
  if (q.contains('ship') || q.contains('track') || text.contains('شحن') || text.contains('تتبع')) {
    body = {
      'intent': 'shipment_status',
      'answer_text': ar ? 'شحنتك في الطريق وتصل بعد حوالي 12 يوماً.' : 'Your shipment is on its way, about 12 days out.',
      'cards': [
        {
          'type': 'shipment_status',
          'title': 'Shipment MSKU1234567',
          'title_ar': 'الشحنة MSKU1234567',
          'severity': 'info',
          'rows': [
            _row('status', 'Status', 'الحالة', 'In transit', 'في الطريق'),
            _row('progress', 'Progress', 'التقدم', '55%'),
            _row('eta', 'ETA', 'موعد الوصول المتوقع', '2026-10-26'),
            _row('route', 'Route', 'المسار', 'Shenzhen → Basra', 'شنتشن ← البصرة'),
          ],
          'refs': {'shipment_id': 'shp_demo01', 'reference': 'MSKU1234567'},
        },
      ],
      'warnings': <String>[],
    };
  } else if (q.contains('deal') || text.contains('صفقة')) {
    body = {
      'intent': 'deal_status',
      'answer_text': ar ? 'الصفقة قيد التنفيذ والدفعة الأولى مؤكدة.' : 'The deal is in fulfilment and the first payment is confirmed.',
      'cards': [
        {
          'type': 'deal_status',
          'title': 'Deal deal_demo01',
          'title_ar': 'الصفقة deal_demo01',
          'severity': 'ok',
          'rows': [
            _row('status', 'Status', 'الحالة', 'In fulfilment', 'قيد التنفيذ'),
            _row('payment', 'Payment', 'الدفع', 'Deposit paid', 'تم دفع العربون'),
          ],
          'refs': {'deal_id': 'deal_demo01'},
        },
      ],
      'warnings': <String>[],
    };
  } else if (q.contains('compare') || text.contains('قارن') || text.contains('مقارنة')) {
    body = {
      'intent': 'compare',
      'answer_text': ar ? 'العرض الأول أرخص والثاني أعلى ثقة.' : 'Listing 1 is cheaper, listing 2 has higher trust.',
      'cards': [
        {
          'type': 'listing_comparison',
          'title': 'Listing comparison',
          'title_ar': 'مقارنة العروض',
          'severity': 'info',
          'columns': [
            {'id': 'lst_001', 'title': 'Wireless Earbuds TWS', 'title_ar': 'سماعات لاسلكية TWS'},
            {'id': 'lst_009', 'title': 'Smart Watch Tracker', 'title_ar': 'ساعة ذكية'},
          ],
          'rows': [
            {
              'key': 'price',
              'label': 'Unit price',
              'label_ar': 'سعر الوحدة',
              'values': ['USD 5.50', 'USD 12.00'],
              'highlight': 0,
            },
            {
              'key': 'trust',
              'label': 'Trust score',
              'label_ar': 'درجة الثقة',
              'values': ['82/100', '91/100'],
              'highlight': 1,
            },
          ],
          'refs': {'listing_a': 'lst_001', 'listing_b': 'lst_009'},
          'footnote': 'Indicative comparison from catalog data.',
          'footnote_ar': 'مقارنة استرشادية من بيانات الكتالوج.',
        },
      ],
      'warnings': <String>[],
    };
  } else if (q.contains('rfq') || q.contains('request') || text.contains('طلب شراء')) {
    body = {
      'intent': 'create_rfq_draft',
      'answer_text': ar
          ? 'جهزت مسودة طلب الشراء. راجعها وانشرها من تبويب الطلبات (لم أنشر شيئاً).'
          : 'I prepared a purchase request draft. Review it and publish it from the Requests tab (nothing was posted).',
      'cards': [
        {
          'type': 'rfq_draft',
          'title': 'Purchase request draft',
          'title_ar': 'مسودة طلب شراء',
          'severity': 'info',
          'rows': [
            _row('product', 'Product', 'المنتج', 'LED lights', 'LED lights'),
            _row('quantity', 'Quantity', 'الكمية', '500'),
            _row('unit', 'Unit', 'الوحدة', 'piece', 'قطعة'),
            _row('destination', 'Delivery to', 'جهة التسليم', 'Baghdad', 'بغداد'),
          ],
          'refs': {
            'deep_link': '/requests/new',
            'draft': 'true',
            'missing': '',
            'prefill_product': 'LED lights',
            'prefill_quantity': '500',
            'prefill_unit': 'piece',
            'prefill_destination': 'Baghdad',
          },
          'footnote': 'Draft only: nothing has been posted. Review and publish it from the Requests tab.',
          'footnote_ar': 'مسودة فقط: لم يُنشر شيء. راجعها وانشرها من تبويب الطلبات.',
        },
      ],
      'warnings': <String>[],
    };
  } else if (q.contains('hs') || text.contains('جمرك') || text.contains('رمز')) {
    body = {
      'intent': 'hs_lookup',
      'answer_text': ar ? 'أقرب رمز جمركي: 8518.30.' : 'Closest HS code: 8518.30.',
      'cards': [
        {
          'type': 'hs_code',
          'title': 'HS code lookup',
          'title_ar': 'البحث عن الرمز الجمركي',
          'severity': 'info',
          'rows': [
            _row('code', 'Code', 'الرمز', '8518.30'),
            _row('duty', 'Typical duty', 'الرسوم التقريبية', '~5%'),
          ],
          'refs': {'hs_code': '851830', 'destination_country': 'IQ'},
        },
      ],
      'warnings': <String>[],
    };
  } else {
    body = {
      'intent': 'help',
      'answer_text': ar
          ? 'أستطيع متابعة شحنة أو صفقة، أو مقارنة عرضين، أو البحث عن رمز جمركي.'
          : 'I can follow a shipment or a deal, compare two listings, or look up an HS code.',
      'cards': <Map<String, dynamic>>[],
      'warnings': <String>[],
    };
  }
  return AssistantAnswer.fromJson(body);
}
