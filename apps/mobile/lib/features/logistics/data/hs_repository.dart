import 'package:factory_finder/core/api/api_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// One HS code suggestion from GET /v1/hs/search.
class HsItem {
  const HsItem({
    required this.code,
    this.chapter = '',
    this.descriptionEn = '',
    this.descriptionAr = '',
    this.dutyHintPercent,
    this.keywords = const [],
  });

  final String code;
  final String chapter;
  final String descriptionEn;
  final String descriptionAr;

  /// Typical duty rate hint in percent (an estimate, never authoritative).
  final double? dutyHintPercent;
  final List<String> keywords;

  String description(String languageCode) =>
      languageCode == 'ar' && descriptionAr.isNotEmpty ? descriptionAr : descriptionEn;

  factory HsItem.fromJson(Map<String, dynamic> j) => HsItem(
        code: (j['code'] ?? '').toString(),
        chapter: (j['chapter'] ?? '').toString(),
        descriptionEn: (j['description_en'] ?? '').toString(),
        descriptionAr: (j['description_ar'] ?? '').toString(),
        dutyHintPercent: _toDouble(j['typical_duty_percent_hint']),
        keywords: ((j['keywords'] as List?) ?? const [])
            .map((e) => e.toString())
            .toList(),
      );
}

double? _toDouble(Object? v) {
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v);
  return null;
}

class HsSearchResult {
  const HsSearchResult({
    this.items = const [],
    this.total = 0,
    this.destinationCountry,
    this.disclaimer = '',
  });

  final List<HsItem> items;
  final int total;
  final String? destinationCountry;
  final String disclaimer;

  factory HsSearchResult.fromJson(Map<String, dynamic> j) {
    final items = ((j['items'] as List?) ?? const [])
        .whereType<Map>()
        .map((e) => HsItem.fromJson(Map<String, dynamic>.from(e)))
        .toList();
    return HsSearchResult(
      items: items,
      total: (j['total'] as num?)?.toInt() ?? items.length,
      destinationCountry: j['destination_country'] as String?,
      disclaimer: (j['disclaimer'] ?? '').toString(),
    );
  }
}

/// Small in-memory HS list for mock mode and tests.
const List<HsItem> kMockHsItems = [
  HsItem(code: '851830', chapter: '85', descriptionEn: 'Headphones and earphones', descriptionAr: 'سماعات رأس وأذن', dutyHintPercent: 5, keywords: ['earbuds', 'headphones', 'bluetooth']),
  HsItem(code: '940540', chapter: '94', descriptionEn: 'Electric lamps and lighting fittings', descriptionAr: 'مصابيح وتجهيزات إنارة كهربائية', dutyHintPercent: 10, keywords: ['led', 'lamp', 'street light']),
  HsItem(code: '610910', chapter: '61', descriptionEn: 'T-shirts, knitted, of cotton', descriptionAr: 'قمصان تي شيرت قطنية', dutyHintPercent: 15, keywords: ['t-shirt', 'cotton', 'apparel']),
  HsItem(code: '540754', chapter: '54', descriptionEn: 'Woven fabrics of synthetic filament yarn', descriptionAr: 'أقمشة منسوجة من خيوط صناعية', dutyHintPercent: 10, keywords: ['fabric', 'polyester', 'curtain']),
  HsItem(code: '940130', chapter: '94', descriptionEn: 'Swivel seats with variable height', descriptionAr: 'كراسي دوّارة قابلة لتعديل الارتفاع', dutyHintPercent: 20, keywords: ['chair', 'office', 'furniture']),
  HsItem(code: '481910', chapter: '48', descriptionEn: 'Cartons and boxes of corrugated paper', descriptionAr: 'كراتين وعلب من الورق المموّج', dutyHintPercent: 10, keywords: ['carton', 'box', 'packaging']),
  HsItem(code: '392190', chapter: '39', descriptionEn: 'Plastic plates, sheets and film', descriptionAr: 'ألواح وصفائح وأغشية بلاستيكية', dutyHintPercent: 10, keywords: ['plastic', 'film', 'stretch']),
  HsItem(code: '910212', chapter: '91', descriptionEn: 'Wrist-watches, electronic display', descriptionAr: 'ساعات يد إلكترونية', dutyHintPercent: 10, keywords: ['watch', 'smart watch']),
  HsItem(code: '390120', chapter: '39', descriptionEn: 'Polyethylene, specific gravity 0.94 or more', descriptionAr: 'بولي إيثيلين عالي الكثافة', dutyHintPercent: 5, keywords: ['hdpe', 'resin', 'polyethylene']),
  HsItem(code: '720836', chapter: '72', descriptionEn: 'Flat-rolled iron or steel, hot-rolled', descriptionAr: 'حديد أو صلب مسطّح مدرفل على الساخن', dutyHintPercent: 5, keywords: ['steel', 'coil', 'hot rolled']),
  HsItem(code: '721420', chapter: '72', descriptionEn: 'Bars and rods of iron or steel (rebar)', descriptionAr: 'قضبان وأسياخ حديد التسليح', dutyHintPercent: 5, keywords: ['rebar', 'steel', 'bars']),
  HsItem(code: '760110', chapter: '76', descriptionEn: 'Unwrought aluminium, not alloyed', descriptionAr: 'ألمنيوم خام غير مخلوط', dutyHintPercent: 5, keywords: ['aluminum', 'aluminium', 'ingot']),
  HsItem(code: '847730', chapter: '84', descriptionEn: 'Blow moulding machines', descriptionAr: 'آلات نفخ القوالب', dutyHintPercent: 5, keywords: ['blow', 'pet', 'bottle', 'machine']),
  HsItem(code: '847710', chapter: '84', descriptionEn: 'Injection-moulding machines', descriptionAr: 'آلات حقن القوالب', dutyHintPercent: 5, keywords: ['injection', 'molding', 'machine']),
  HsItem(code: '845810', chapter: '84', descriptionEn: 'Horizontal lathes, numerically controlled', descriptionAr: 'مخارط أفقية رقمية CNC', dutyHintPercent: 5, keywords: ['lathe', 'cnc', 'machine tool']),
];

/// Pure mock search: code prefix, description or keyword substring.
HsSearchResult searchMockHs(String q, {String? destinationCountry, int limit = 10}) {
  final text = q.trim().toLowerCase();
  final matches = text.isEmpty
      ? <HsItem>[]
      : kMockHsItems.where((i) {
          final hay = '${i.descriptionEn} ${i.descriptionAr} ${i.keywords.join(' ')}'
              .toLowerCase();
          return i.code.startsWith(text) || hay.contains(text);
        }).toList();
  return HsSearchResult(
    items: matches.take(limit).toList(),
    total: matches.length,
    destinationCountry: destinationCountry,
  );
}

class HsRepository {
  HsRepository(this._api);

  final ApiClient _api;

  Future<HsSearchResult> search(
    String q, {
    String? destinationCountry,
    int limit = 10,
  }) async {
    if (_api.isMock) {
      await mockDelay(120);
      return searchMockHs(q, destinationCountry: destinationCountry, limit: limit);
    }
    final json = await _api.get('/v1/hs/search', query: {
      'q': q,
      'limit': limit,
      if (destinationCountry != null) 'destination_country': destinationCountry,
    });
    return HsSearchResult.fromJson(Map<String, dynamic>.from(json as Map));
  }
}

final hsRepositoryProvider = Provider<HsRepository>(
  (ref) => HsRepository(ref.watch(apiClientProvider)),
);
