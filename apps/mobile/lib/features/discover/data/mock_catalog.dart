import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/search_facets.dart';

TrustBand _bandFor(int score) =>
    score >= 75 ? TrustBand.green : (score >= 50 ? TrustBand.yellow : TrustBand.red);

SupplierSummary _sup(
  String id,
  String name,
  String cc,
  String city,
  int years,
  bool verified,
  int score,
) =>
    SupplierSummary(
      id: id,
      name: name,
      location: Location(countryCode: cc, city: city),
      yearsInBusiness: years,
      verified: verified,
      trustScore: score,
      trustBand: _bandFor(score),
    );

final Map<String, SupplierSummary> mockSuppliers = {
  for (final s in [
    _sup('sup_cn_001', 'Shenzhen Brightway Electronics Co.', 'CN', 'Shenzhen', 9, true, 86),
    _sup('sup_cn_002', 'Guangzhou Hualian Textiles', 'CN', 'Guangzhou', 12, true, 91),
    _sup('sup_cn_003', 'Foshan Dingsheng Machinery', 'CN', 'Foshan', 15, true, 78),
    _sup('sup_cn_004', 'Yiwu Sunrise Trading', 'CN', 'Yiwu', 4, false, 63),
    _sup('sup_cn_005', 'Ningbo Hengtai Plastics', 'CN', 'Ningbo', 7, true, 82),
    _sup('sup_cn_006', 'Tangshan Ironbridge Steel', 'CN', 'Tangshan', 11, true, 71),
    _sup('sup_cn_007', 'Dongguan QuickPack', 'CN', 'Dongguan', 2, false, 41),
    _sup('sup_cn_008', 'Zhejiang Greenfield Chemicals', 'CN', 'Hangzhou', 5, false, 58),
    _sup('sup_de_001', 'Bavaria Maschinenbau GmbH', 'DE', 'Munich', 31, true, 93),
    _sup('sup_it_001', 'Emilia Food Machinery SRL', 'IT', 'Parma', 24, true, 88),
    _sup('sup_tr_001', 'Bursa Tekstil A.S.', 'TR', 'Bursa', 18, true, 79),
    _sup('sup_us_001', 'Midwest Used Equipment LLC', 'US', 'Chicago', 14, true, 74),
  ])
    s.id: s,
};

Listing _l(
  int n,
  ListingKind kind,
  ItemCondition cond,
  String title,
  String titleAr,
  String cat,
  String pmin,
  String pmax,
  String unit,
  int moq,
  Incoterm inc,
  double kg,
  double m3,
  String hs,
  int lead1,
  int lead2,
  String sup, {
  String cur = 'USD',
}) {
  final id = 'lst_${n.toString().padLeft(3, '0')}';
  final supplier = mockSuppliers[sup]!;
  return Listing(
    id: id,
    source: 'mock',
    kind: kind,
    condition: cond,
    title: title,
    titleAr: titleAr,
    category: cat,
    images: [
      'https://picsum.photos/seed/ff${n}a/600/450',
      'https://picsum.photos/seed/ff${n}b/600/450',
      'https://picsum.photos/seed/ff${n}c/600/450',
    ],
    price: MoneyRange(
      min: Money(amount: pmin, currency: cur),
      max: Money(amount: pmax, currency: cur),
    ),
    unit: unit,
    moq: moq,
    incoterm: inc,
    unitWeightKg: kg,
    unitVolumeM3: m3,
    hsCode: hs,
    leadTimeDays: DayRange(min: lead1, max: lead2),
    supplier: supplier,
    origin: supplier.location,
  );
}

const _p = ListingKind.product;
const _r = ListingKind.rawMaterial;
const _pl = ListingKind.productionLine;
const _new = ItemCondition.brandNew;
const _used = ItemCondition.used;

final List<Listing> mockListings = [
  _l(1, _p, _new, 'Wireless Bluetooth Earbuds TWS', 'سماعات بلوتوث لاسلكية TWS', 'electronics', '4.20', '6.80', 'piece', 500, Incoterm.fob, 0.06, 0.0002, '851830', 10, 20, 'sup_cn_001'),
  _l(2, _p, _new, 'Solar LED Street Light 60W', 'إنارة شوارع LED بالطاقة الشمسية 60 واط', 'electronics', '38.00', '55.00', 'piece', 50, Incoterm.exw, 9, 0.06, '940540', 15, 25, 'sup_cn_001'),
  _l(3, _p, _new, 'Plain Cotton T-Shirts, Bulk', 'تيشيرتات قطنية سادة بالجملة', 'textiles', '1.90', '3.10', 'piece', 1000, Incoterm.fob, 0.18, 0.0009, '610910', 12, 20, 'sup_cn_002'),
  _l(4, _p, _new, 'Polyester Curtain Fabric Roll', 'قماش ستائر بوليستر (رول)', 'textiles', '1.40', '2.20', 'm', 2000, Incoterm.fob, 0.35, 0.0012, '540754', 15, 25, 'sup_cn_002'),
  _l(5, _p, _new, 'Ergonomic Office Chair', 'كرسي مكتب مريح', 'furniture', '42.00', '68.00', 'piece', 100, Incoterm.fob, 14, 0.22, '940130', 20, 30, 'sup_cn_003'),
  _l(6, _p, _new, '3-Piece Fabric Sofa Set', 'طقم كنب 3 قطع قماش', 'furniture', '310.00', '480.00', 'set', 20, Incoterm.fob, 95, 1.9, '940161', 25, 35, 'sup_cn_003'),
  _l(7, _p, _new, 'Corrugated Shipping Cartons', 'كراتين شحن مضلعة', 'packaging', '0.25', '0.60', 'piece', 5000, Incoterm.exw, 0.4, 0.004, '481910', 7, 12, 'sup_cn_007'),
  _l(8, _p, _new, 'PE Stretch Film Pallet Wrap', 'ستريتش فيلم للتغليف', 'packaging', '12.00', '16.50', 'roll', 300, Incoterm.fob, 2.5, 0.008, '392190', 10, 18, 'sup_cn_005'),
  _l(9, _p, _new, 'Smart Watch Fitness Tracker', 'ساعة ذكية لتتبع اللياقة', 'electronics', '9.50', '14.20', 'piece', 300, Incoterm.fob, 0.12, 0.0004, '910212', 10, 18, 'sup_cn_004'),
  _l(10, _r, _new, 'HDPE Resin Granules, Injection Grade', 'حبيبات بولي إيثيلين HDPE', 'plastic_resin', '1050.00', '1180.00', 'ton', 20, Incoterm.cfr, 1000, 1.6, '390120', 10, 20, 'sup_cn_005'),
  _l(11, _r, _new, 'PVC Resin SG-5', 'مسحوق PVC درجة SG-5', 'plastic_resin', '780.00', '860.00', 'ton', 25, Incoterm.cif, 1000, 1.5, '390410', 12, 22, 'sup_cn_005'),
  _l(12, _r, _new, 'Hot-Rolled Steel Coil (HRC)', 'لفائف حديد ساخنة HRC', 'steel', '520.00', '590.00', 'ton', 50, Incoterm.fob, 1000, 0.45, '720836', 15, 25, 'sup_cn_006'),
  _l(13, _r, _new, 'Rebar Steel Bars 12mm', 'حديد تسليح 12 ملم', 'steel', '480.00', '540.00', 'ton', 100, Incoterm.fob, 1000, 0.4, '721420', 14, 24, 'sup_cn_006'),
  _l(14, _r, _new, 'Aluminum Ingot A7 99.7%', 'سبائك ألمنيوم A7 نقاوة 99.7%', 'aluminum', '2350.00', '2520.00', 'ton', 20, Incoterm.fob, 1000, 0.37, '760110', 15, 25, 'sup_cn_006'),
  _l(15, _r, _new, 'Combed Cotton Yarn Ne 30/1', 'خيوط قطن ممشطة Ne 30/1', 'cotton', '3.40', '4.10', 'kg', 500, Incoterm.fob, 1, 0.0025, '520512', 10, 18, 'sup_tr_001'),
  _l(16, _r, _new, 'Caustic Soda Flakes 99%', 'صودا كاوية قشور 99%', 'chemicals', '380.00', '450.00', 'ton', 25, Incoterm.fob, 1000, 0.8, '281511', 12, 20, 'sup_cn_008'),
  _l(17, _pl, _new, 'Automatic PET Bottle Blowing Line, 6000 BPH', 'خط نفخ زجاجات PET أوتوماتيكي (6000 زجاجة/ساعة)', 'plastics_machinery', '28000.00', '36000.00', 'line', 1, Incoterm.fob, 4200, 14, '847730', 40, 60, 'sup_cn_003'),
  _l(18, _pl, _used, 'Used Injection Molding Machine 250T (2018)', 'ماكينة حقن بلاستيك 250 طن مستعملة (2018)', 'plastics_machinery', '14500.00', '17500.00', 'set', 1, Incoterm.fob, 9500, 18, '847710', 20, 35, 'sup_cn_003'),
  _l(19, _pl, _new, 'Pasta Production Line 500 kg/h', 'خط إنتاج معكرونة 500 كغم/ساعة', 'food_processing', '112000.00', '138000.00', 'line', 1, Incoterm.fca, 12000, 38, '843859', 60, 90, 'sup_it_001', cur: 'EUR'),
  _l(20, _pl, _used, 'Used Filling & Capping Line (2015)', 'خط تعبئة وإغلاق مستعمل (2015)', 'packaging_machinery', '32000.00', '41000.00', 'line', 1, Incoterm.exw, 6800, 24, '842240', 15, 30, 'sup_de_001', cur: 'EUR'),
  _l(21, _pl, _used, 'Used Mazak CNC Lathe (2016)', 'مخرطة CNC مازاك مستعملة (2016)', 'metalworking', '21000.00', '26500.00', 'set', 1, Incoterm.fca, 5200, 11, '845810', 15, 25, 'sup_us_001'),
  _l(22, _pl, ItemCondition.refurbished, 'Refurbished Bread Bakery Line 1200/h', 'خط مخابز مجدد 1200 رغيف/ساعة', 'food_processing', '46000.00', '58000.00', 'line', 1, Incoterm.fca, 7800, 26, '843810', 25, 40, 'sup_it_001', cur: 'EUR'),
  _l(23, _pl, _new, 'Plastic Bag Extrusion Machine', 'ماكينة بثق أكياس بلاستيك', 'plastics_machinery', '9800.00', '13500.00', 'set', 1, Incoterm.fob, 2100, 6, '847720', 25, 40, 'sup_cn_003'),
  _l(24, _pl, _used, 'Used Metal Stamping Press 160T', 'مكبس تشكيل معادن 160 طن مستعمل', 'metalworking', '11500.00', '15000.00', 'set', 1, Incoterm.exw, 8500, 14, '846299', 10, 20, 'sup_us_001'),
];

/// Deterministic trust breakdown. Impacts always add up to `score - 50`.
TrustScore mockTrustFor(SupplierSummary s) {
  final score = s.trustScore ?? 50;
  final years = s.yearsInBusiness ?? 0;
  final factors = <TrustFactor>[
    TrustFactor(
      key: 'business_verification',
      impact: s.verified ? 16 : -8,
      explanation: s.verified
          ? 'Business licence verified.'
          : 'Business licence not verified.',
      explanationAr: s.verified
          ? 'تم التحقق من الترخيص التجاري للمورد.'
          : 'لم يتم التحقق من الترخيص التجاري بعد.',
    ),
    TrustFactor(
      key: 'years_in_business',
      impact: years >= 10 ? 12 : (years >= 5 ? 6 : -4),
      explanation: '$years years in business.',
      explanationAr: 'خبرة المورد في السوق $years سنة.',
    ),
    TrustFactor(
      key: 'complaints',
      impact: score >= 75 ? 4 : (score >= 50 ? -2 : -9),
      explanation: score >= 75
          ? 'Very few buyer complaints.'
          : 'Some buyer complaints on record.',
      explanationAr: score >= 75
          ? 'عدد الشكاوى من المشترين قليل جداً.'
          : 'توجد شكاوى مسجلة من مشترين سابقين.',
    ),
  ];
  final used = factors.fold<int>(0, (a, f) => a + f.impact);
  final rest = score - 50 - used;
  factors.add(
    TrustFactor(
      key: 'delivery_and_reviews',
      impact: rest,
      explanation: rest >= 0
          ? 'On-time delivery and positive buyer reviews.'
          : 'Late deliveries and weaker buyer reviews.',
      explanationAr: rest >= 0
          ? 'التزام بمواعيد التسليم وتقييمات إيجابية من المشترين.'
          : 'تأخر في بعض التسليمات وتقييمات أضعف من المشترين.',
    ),
  );
  return TrustScore(
    supplierId: s.id,
    score: score,
    band: _bandFor(score),
    factors: factors,
    confidence: s.verified ? 82 : 40,
    dataGaps: s.verified
        ? const <TrustDataGap>[]
        : const [
            TrustDataGap(
              key: 'third_party_audit',
              label: 'Third-party factory audit',
              labelAr: 'تدقيق مصنع من طرف ثالث',
            ),
          ],
    flags: score < 50 ? const ['price_anomaly'] : const <String>[],
    modelVersion: 'mock-v2',
  );
}

bool _matches(Listing l, ListingQuery q) {
  if (q.kind != null && l.kind != q.kind) return false;
  if (q.condition != null && l.condition != q.condition) return false;
  if (q.originCountry != null && l.origin?.countryCode != q.originCountry) {
    return false;
  }
  if (q.maxMoq != null && (l.moq ?? 0) > q.maxMoq!) return false;
  if (q.verifiedOnly && !l.supplier.verified) return false;
  // Overlap test on the unit price range (mock prices are compared as-is).
  if (q.minPrice != null && l.price.max.value < q.minPrice!) return false;
  if (q.maxPrice != null && l.price.min.value > q.maxPrice!) return false;
  if (q.category != null && l.category != q.category) return false;
  if (q.supplierId != null && l.supplier.id != q.supplierId) return false;
  final text = q.query.trim().toLowerCase();
  if (text.isNotEmpty) {
    final hay = '${l.title} ${l.titleAr ?? ''} ${l.category ?? ''} ${l.supplier.name}'
        .toLowerCase();
    if (!text.split(RegExp(r'\s+')).every(hay.contains)) return false;
  }
  return true;
}

/// Filters + sorts the mock catalogue (pure function, used by tests).
PageResult<Listing> filterMockListings(ListingQuery q) {
  final items = mockListings.where((l) => _matches(l, q)).toList();
  switch (q.sort) {
    case SortOption.relevance:
      break;
    case SortOption.priceLow:
      items.sort((a, b) => a.price.min.value.compareTo(b.price.min.value));
    case SortOption.priceHigh:
      items.sort((a, b) => b.price.max.value.compareTo(a.price.max.value));
    case SortOption.trust:
      items.sort((a, b) =>
          (b.supplier.trustScore ?? 0).compareTo(a.supplier.trustScore ?? 0));
    case SortOption.moq:
      items.sort((a, b) => (a.moq ?? 1 << 30).compareTo(b.moq ?? 1 << 30));
  }
  final textOnly = mockListings.where((l) => _matches(l, ListingQuery(query: q.query))).toList();
  return ListingPage(
    items: items,
    total: items.length,
    page: 1,
    pageSize: 50,
    facets: SearchFacets.fromListings(textOnly),
  );
}
