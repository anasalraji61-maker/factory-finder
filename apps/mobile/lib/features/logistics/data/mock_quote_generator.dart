import 'dart:math' as math;

import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';

/// Mock FX table: units of currency per 1 USD.
const Map<String, double> kUsdRates = {
  'USD': 1,
  'EUR': 0.92,
  'CNY': 7.2,
  'IQD': 1310,
  'TRY': 41,
  'AED': 3.6725,
  'SAR': 3.75,
  'GBP': 0.78,
};

const String _kSource = 'mock-rate-table-2026Q4';

String _region(String cc) {
  switch (cc) {
    case 'CN':
    case 'IN':
    case 'VN':
      return 'asia';
    case 'IQ':
    case 'AE':
    case 'SA':
    case 'KW':
    case 'JO':
    case 'EG':
      return 'me';
    case 'US':
      return 'na';
    default:
      return 'eu'; // TR, DE, IT, ...
  }
}

double _laneFactor(String o, String d) {
  final ro = _region(o);
  final rd = _region(d);
  if (o == d) return 0.3;
  if (ro == rd) return ro == 'asia' ? 0.4 : 0.35;
  final key = '$ro>$rd';
  const table = {
    'asia>me': 1.0,
    'asia>eu': 1.2,
    'asia>na': 1.3,
    'eu>me': 0.7,
    'me>eu': 0.7,
    'eu>asia': 1.15,
    'eu>na': 1.1,
    'na>eu': 1.1,
    'na>me': 1.3,
    'na>asia': 1.3,
    'me>asia': 1.0,
  };
  return table[key] ?? 1.0;
}

(int, int) _seaDays(String o, String d) {
  final ro = _region(o);
  final rd = _region(d);
  if (ro == rd) return (6, 12);
  if (ro == 'asia' && rd == 'me') return (30, 42);
  if (ro == 'asia' && rd == 'eu') return (32, 45);
  if (ro == 'asia' && rd == 'na') return (26, 38);
  if (ro == 'eu' && rd == 'me') return (12, 20);
  return (25, 40);
}

String _seaPort(Location l) {
  final city = (l.city ?? '').toLowerCase();
  switch (l.countryCode) {
    case 'CN':
      if (city.contains('guangzhou') || city.contains('foshan')) return 'Nansha (CNNSH)';
      if (city.contains('shenzhen') || city.contains('dongguan')) return 'Yantian (CNYTN)';
      if (city.contains('ningbo') || city.contains('yiwu') || city.contains('hangzhou')) {
        return 'Ningbo-Zhoushan (CNNGB)';
      }
      if (city.contains('tangshan') || city.contains('tianjin')) return 'Tianjin (CNTSN)';
      return 'Shanghai (CNSHA)';
    case 'TR':
      return 'Mersin (TRMER)';
    case 'AE':
      return 'Jebel Ali (AEJEA)';
    case 'SA':
      return 'Jeddah (SAJED)';
    case 'DE':
      return 'Hamburg (DEHAM)';
    case 'IT':
      return 'Genoa (ITGOA)';
    case 'US':
      return 'Los Angeles (USLAX)';
    case 'EG':
      return 'Alexandria (EGALY)';
    case 'JO':
      return 'Aqaba (JOAQJ)';
    case 'KW':
      return 'Shuwaikh (KWSWK)';
    case 'IN':
      return 'Nhava Sheva (INNSA)';
    case 'IQ':
      return 'Umm Qasr (IQUQR)';
  }
  return '${l.city ?? l.countryCode} port';
}

const List<String> _iraqNorth = ['erbil', 'arbil', 'sulaymaniyah', 'duhok', 'dohuk', 'mosul', 'kirkuk', 'أربيل', 'اربيل', 'السليمانية', 'دهوك', 'الموصل', 'كركوك'];

bool _isIraqNorth(Location l) =>
    l.countryCode == 'IQ' &&
    _iraqNorth.any((c) => (l.city ?? '').toLowerCase().contains(c));

double _dutyRate(String? hs) {
  if (hs == null || hs.length < 2) return 0.10;
  switch (hs.substring(0, 2)) {
    case '84':
    case '85':
    case '90':
      return 0.05;
    case '28':
    case '39':
    case '72':
    case '76':
      return 0.05;
    case '52':
    case '54':
    case '61':
    case '62':
    case '63':
      return 0.15;
    case '94':
      return 0.20;
    default:
      return 0.10;
  }
}

double _taxRate(String cc) {
  switch (cc) {
    case 'IQ':
      return 0.01;
    case 'DE':
      return 0.19;
    case 'IT':
      return 0.22;
    case 'TR':
      return 0.20;
    case 'AE':
      return 0.05;
    case 'SA':
      return 0.15;
    case 'US':
      return 0.0;
    default:
      return 0.10;
  }
}

/// Deterministic landed-cost generator used while FF_MOCK=true and in tests.
class MockQuoteGenerator {
  MockQuoteGenerator._();

  static double _convert(double usd, String currency) =>
      usd * (kUsdRates[currency] ?? 1);

  static LandedCostQuote generate(
    QuoteRequest r, {
    String lang = 'ar',
    DateTime? now,
  }) {
    String t(String en, String ar) => lang == 'ar' ? ar : en;
    final cur = r.displayCurrency;
    final fx = kUsdRates[cur] ?? 1;
    final goodsUsd = r.goodsValue / (kUsdRates[r.goodsCurrency] ?? 1);
    final oCc = r.origin.countryCode;
    final dCc = r.destination.countryCode;
    final lf = _laneFactor(oCc, dCc);
    final weight = r.weightKg <= 0 ? 1.0 : r.weightKg;
    final cbm = r.volumeM3 <= 0 ? math.max(0.1, weight / 500) : r.volumeM3;
    final lclCbm = math.max(cbm, weight / 1000);
    final airKg = math.max(weight, cbm * 167);
    final oCity = r.origin.city ?? oCc;
    final dCity = r.destination.city ?? dCc;
    final north = _isIraqNorth(r.destination);
    final inc = r.incoterm;

    final inclOriginInland = inc != Incoterm.exw;
    final inclOriginHandling = inc != Incoterm.exw && inc != Incoterm.fca;
    final inclMain = inc == Incoterm.cfr ||
        inc == Incoterm.cif ||
        inc == Incoterm.dap ||
        inc == Incoterm.ddp;
    final inclInsurance = inc == Incoterm.cif || inc == Incoterm.dap || inc == Incoterm.ddp;
    final inclDutiesAndInland = inc == Incoterm.ddp;
    final inclDestInland = inc == Incoterm.dap || inc == Incoterm.ddp;

    // Which modes are applicable.
    final wanted = r.modes;
    bool want(TransportMode m, bool auto) => wanted.isEmpty ? auto : wanted.contains(m);
    final canRail = (oCc == 'CN' && (_region(dCc) == 'eu' || _region(dCc) == 'me')) ||
        (dCc == 'CN' && _region(oCc) == 'eu');
    final ro = _region(oCc);
    final rd = _region(dCc);
    final canRoad = oCc == dCc ||
        (ro == rd && ro != 'na') ||
        (ro == 'eu' && rd == 'me') ||
        (ro == 'me' && rd == 'eu');
    final modes = <TransportMode>[
      if (want(TransportMode.seaLcl, lclCbm <= 25)) TransportMode.seaLcl,
      if (want(TransportMode.seaFcl20, lclCbm >= 10)) TransportMode.seaFcl20,
      if (want(TransportMode.seaFcl40, lclCbm >= 24)) TransportMode.seaFcl40,
      if (want(TransportMode.seaFcl40hc, lclCbm >= 24)) TransportMode.seaFcl40hc,
      if (want(TransportMode.air, weight <= 5000)) TransportMode.air,
      if (canRail && want(TransportMode.rail, lclCbm <= 60)) TransportMode.rail,
      if (canRoad && want(TransportMode.road, weight <= 25000)) TransportMode.road,
    ];

    final options = <LandedCostOption>[];
    for (final mode in modes) {
      final isSea = mode == TransportMode.seaLcl ||
          mode == TransportMode.seaFcl20 ||
          mode == TransportMode.seaFcl40 ||
          mode == TransportMode.seaFcl40hc;
      final isFcl = isSea && mode != TransportMode.seaLcl;

      // Containers / trucks.
      var units = 1;
      if (mode == TransportMode.seaFcl20) {
        units = math.max((cbm / 28).ceil(), (weight / 24000).ceil());
      } else if (mode == TransportMode.seaFcl40) {
        units = math.max((cbm / 58).ceil(), (weight / 26000).ceil());
      } else if (mode == TransportMode.seaFcl40hc) {
        units = math.max((cbm / 68).ceil(), (weight / 26000).ceil());
      } else if (mode == TransportMode.road) {
        units = math.max(1, math.max((cbm / 80).ceil(), (weight / 24000).ceil()));
      }
      units = math.max(1, units);

      // Main leg.
      double mainUsd;
      switch (mode) {
        case TransportMode.seaLcl:
          mainUsd = math.max(120.0, lclCbm * 62 * lf);
        case TransportMode.seaFcl20:
          mainUsd = units * 1900 * lf;
        case TransportMode.seaFcl40:
          mainUsd = units * 2900 * lf;
        case TransportMode.seaFcl40hc:
          mainUsd = units * 3100 * lf;
        case TransportMode.air:
          mainUsd = math.max(180.0, airKg * 5.4 * lf);
        case TransportMode.rail:
          mainUsd = math.max(250.0, lclCbm * 110 * lf);
        case TransportMode.road:
          mainUsd = math.max(300.0, units * 600 * math.max(lf, 0.4) * 2);
      }

      // Other stage costs (USD).
      final originInland = mode == TransportMode.road
          ? 0.0
          : (mode == TransportMode.air ? 60 + 0.03 * weight : 120.0 * units + 0.05 * weight);
      final originHandling = isFcl
          ? 260.0 * units
          : (mode == TransportMode.air
              ? 70 + 0.08 * airKg
              : (mode == TransportMode.road ? 60.0 : 85 + 5 * cbm));
      final destHandling = isFcl
          ? 330.0 * units
          : (mode == TransportMode.air
              ? 80 + 0.1 * airKg
              : (mode == TransportMode.road ? 50.0 : 140 + 7 * cbm));
      final clearance = dCc == 'IQ' ? 380.0 : 220.0;
      final insuranceUsd = r.insurance ? 0.005 * goodsUsd * 1.1 : 0.0;
      final dgUsd = r.dangerousGoods
          ? (mode == TransportMode.air ? 0.35 * mainUsd + 250 : 0.12 * mainUsd + 150)
          : 0.0;

      // Destination plan.
      double inlandFlat;
      var extraMin = 1;
      var extraMax = 3;
      String hub;
      final warnings = <String>[];
      final isAirMode = mode == TransportMode.air;
      if (isAirMode) {
        hub = _airHub(r.destination);
        inlandFlat = 60;
      } else if (dCc == 'IQ' && isSea) {
        if (north) {
          hub = 'Mersin (TRMER)';
          inlandFlat = 1400;
          extraMin = 4;
          extraMax = 8;
          warnings.add(t(
            'Iraq North has no sea access: goods land at Mersin (Türkiye) and continue by truck via the Ibrahim Khalil border. Extra border time is possible.',
            'شمال العراق بلا منفذ بحري: تصل البضاعة إلى ميناء مرسين (تركيا) ثم تُنقل بالشاحنات عبر منفذ إبراهيم الخليل. قد تتأخر عند الحدود.',
          ));
        } else {
          hub = 'Umm Qasr (IQUQR)';
          final c = (dCity).toLowerCase();
          inlandFlat = c.contains('basra') || c.contains('البصرة') ? 120 : 450;
          extraMin = 2;
          extraMax = 5;
          warnings.add(t(
            'Umm Qasr port congestion can add 5–10 days; confirm with your forwarder.',
            'قد يشهد ميناء أم قصر ازدحاماً يضيف 5–10 أيام؛ تأكد من ذلك مع شركة الشحن.',
          ));
        }
      } else if (mode == TransportMode.road || mode == TransportMode.rail) {
        hub = mode == TransportMode.rail ? 'Rail terminal' : 'Border crossing';
        inlandFlat = dCc == 'IQ' ? 600 : 300;
        if (mode == TransportMode.rail && rd == 'me') {
          hub = 'Mersin (TRMER)';
          extraMin = 4;
          extraMax = 9;
          inlandFlat = 1200;
          warnings.add(t(
            'Rail reaches Türkiye; the last leg to ${r.destination.countryCode} is by truck across a border.',
            'السكة الحديد تصل إلى تركيا ثم تُكمل الشاحنات الرحلة عبر الحدود إلى الوجهة.',
          ));
        }
      } else {
        hub = _seaPort(r.destination);
        inlandFlat = 350;
      }
      if (isAirMode) {
        // Airports are close to the city.
        extraMin = 1;
        extraMax = 2;
      }
      final destInland = inlandFlat * units + 0.04 * weight;

      // Base transit days.
      (int, int) base;
      if (isSea) {
        base = _seaDays(oCc, dCc);
      } else if (isAirMode) {
        base = rd == ro ? (2, 4) : (4, 8);
      } else if (mode == TransportMode.rail) {
        base = dCc == 'CN' || rd == 'eu' ? (16, 24) : (22, 32);
      } else {
        base = ro == rd ? (3, 7) : (5, 10);
      }
      final days = DayRange(min: base.$1 + 2 + extraMin, max: base.$2 + 5 + extraMax);

      // Duties / taxes on CIF value.
      final cif = goodsUsd + mainUsd + insuranceUsd;
      final dutyUsd = cif * _dutyRate(r.hsCode);
      final taxUsd = (cif + dutyUsd) * _taxRate(dCc);

      // Warnings.
      if (r.dangerousGoods) {
        warnings.add(t(
          'Dangerous goods: carrier acceptance, special packaging and a surcharge apply.${isAirMode ? ' Air carriers may refuse this cargo.' : ''}',
          'بضاعة خطرة: تحتاج موافقة الناقل وتغليفاً خاصاً مع رسوم إضافية.${isAirMode ? ' قد ترفض شركات الطيران هذه الشحنة.' : ''}',
        ));
      }
      if (mode == TransportMode.seaLcl && cbm > 15) {
        warnings.add(t(
          'Large volume for LCL: a full container may be cheaper.',
          'حجم كبير للشحن المجمّع: قد تكون الحاوية الكاملة أوفر.',
        ));
      }
      if (isAirMode && cbm * 167 > weight * 1.5) {
        warnings.add(t(
          'Volumetric weight applies (1 m³ = 167 kg), which raises the air freight cost.',
          'يُحتسب الوزن الحجمي (1 م³ = 167 كغم) مما يرفع كلفة الشحن الجوي.',
        ));
      }

      // Lines.
      final lines = <CostLine>[];
      void add(String stage, String en, String ar, double usd, {bool estimate = true}) {
        final v = double.parse(_convert(usd, cur).toStringAsFixed(2));
        lines.add(CostLine(
          stage: stage,
          description: t(en, ar),
          amount: Money(amount: v.toStringAsFixed(2), currency: cur),
          estimate: estimate,
          source: _kSource,
          fxRate: '1 USD = ${fx.toStringAsFixed(4)} $cur',
        ));
      }

      final incl = t(' (included in supplier price)', ' (مشمول في سعر المورد)');
      add('goods', 'Goods value', 'قيمة البضاعة', goodsUsd, estimate: false);
      add('origin_inland', 'Inland haul to origin port/hub: $oCity', 'نقل داخلي إلى ميناء/مركز الشحن: $oCity',
          inclOriginInland ? 0 : originInland);
      if (inclOriginInland) {
        lines.last = _withNote(lines.last, incl);
      }
      add('origin_handling', 'Export clearance & handling', 'تخليص التصدير والمناولة',
          inclOriginHandling ? 0 : originHandling);
      if (inclOriginHandling) lines.last = _withNote(lines.last, incl);
      add('main_leg', 'Main freight (${mode.json})', 'الشحن الرئيسي (${mode.json})',
          inclMain ? 0 : mainUsd);
      if (inclMain) lines.last = _withNote(lines.last, incl);
      if (r.insurance) {
        add('insurance', 'Cargo insurance (0.5%)', 'تأمين الشحنة (0.5%)',
            inclInsurance ? 0 : insuranceUsd);
        if (inclInsurance) lines.last = _withNote(lines.last, incl);
      }
      if (dgUsd > 0) {
        add('other', 'Dangerous goods surcharge', 'رسوم إضافية للبضاعة الخطرة', dgUsd);
      }
      add('destination_handling', 'Port/terminal handling at destination', 'مناولة الميناء/المحطة في الوجهة', destHandling);
      add('duties', 'Estimated customs duty (HS ${r.hsCode ?? 'n/a'})', 'جمارك تقديرية (HS ${r.hsCode ?? 'غير محدد'})',
          inclDutiesAndInland ? 0 : dutyUsd);
      if (inclDutiesAndInland) lines.last = _withNote(lines.last, incl);
      add('taxes', 'Estimated taxes & fees', 'ضرائب ورسوم تقديرية', inclDutiesAndInland ? 0 : taxUsd);
      if (inclDutiesAndInland) lines.last = _withNote(lines.last, incl);
      add('clearance', 'Customs clearance & broker fees', 'تخليص جمركي وأجور المخلّص',
          inclDutiesAndInland ? 0 : clearance);
      if (inclDutiesAndInland) lines.last = _withNote(lines.last, incl);
      add('destination_inland', 'Truck from $hub to $dCity', 'نقل بالشاحنات من $hub إلى $dCity',
          inclDestInland ? 0 : destInland);
      if (inclDestInland) lines.last = _withNote(lines.last, incl);

      // Totals (range built from the already-rounded line amounts).
      var minSum = 0.0;
      var maxSum = 0.0;
      for (final l in lines) {
        final v = l.amount.value;
        minSum += l.estimate ? v * 0.92 : v;
        maxSum += l.estimate ? v * 1.12 : v;
      }

      final oPort = isAirMode ? '$oCity airport' : _seaPort(r.origin);
      final arrow = lang == 'ar' ? ' ← ' : ' → ';
      final route = [
        oCity,
        oPort,
        hub,
        dCity,
      ].join(arrow);
      final tonKm = (weight / 1000) *
          (isAirMode
              ? 8000 * lf
              : (isSea ? 10000 * lf : (mode == TransportMode.rail ? 11000 : 2000 * math.max(lf, 0.4))));
      final coef = isAirMode ? 0.6 : (isSea ? 0.012 : (mode == TransportMode.rail ? 0.025 : 0.09));

      options.add(LandedCostOption(
        mode: mode,
        lines: lines,
        total: MoneyRange(
          min: Money(amount: minSum.toStringAsFixed(2), currency: cur),
          max: Money(amount: maxSum.toStringAsFixed(2), currency: cur),
        ),
        transitDays: days,
        originHub: oPort,
        destinationHub: hub,
        routeSummary: route,
        co2Kg: double.parse((tonKm * coef).toStringAsFixed(1)),
        warnings: warnings,
        sensitivity: _sensitivity(
          cur: cur,
          base: (minSum + maxSum) / 2,
          freight: lines
              .where((l) => l.stage == 'main_leg')
              .fold<double>(0, (a, l) => a + l.amount.value),
          goods: _convert(goodsUsd, cur),
          goodsCurrency: r.goodsCurrency,
          ar: lang == 'ar',
        ),
      ));
    }

    // Sort by mid total, then mark the recommended option
    // (cost + capital tied up per transit day).
    double mid(LandedCostOption o) => (o.total.min.value + o.total.max.value) / 2;
    options.sort((a, b) => mid(a).compareTo(mid(b)));
    final goodsDisplay = _convert(goodsUsd, cur);
    double score(LandedCostOption o) =>
        mid(o) + (o.transitDays.min + o.transitDays.max) / 2 * goodsDisplay * 0.0015;
    if (options.isNotEmpty) {
      var best = 0;
      for (var i = 1; i < options.length; i++) {
        if (score(options[i]) < score(options[best])) best = i;
      }
      final o = options[best];
      options[best] = LandedCostOption(
        mode: o.mode,
        lines: o.lines,
        total: o.total,
        transitDays: o.transitDays,
        originHub: o.originHub,
        destinationHub: o.destinationHub,
        routeSummary: o.routeSummary,
        co2Kg: o.co2Kg,
        recommended: true,
        warnings: o.warnings,
        sensitivity: o.sensitivity,
      );
    }

    final created = now ?? DateTime.now();
    final quoteWarnings = <String>[
      if (goodsUsd > 0 && goodsUsd < 150)
        t('Low-value parcel: a de minimis duty exemption may apply in some countries; this estimate still includes duties.',
            'شحنة منخفضة القيمة: قد ينطبق إعفاء جمركي للحد الأدنى في بعض الدول؛ هذا التقدير ما زال يشمل الرسوم.'),
    ];
    return LandedCostQuote(
      id: 'q_${created.millisecondsSinceEpoch}',
      currency: cur,
      options: options,
      createdAt: created,
      origin: r.origin,
      destination: r.destination,
      warnings: quoteWarnings,
      assumptions: [
        t('Mock rate table — not a binding quote. All logistics lines are estimates (range −8% / +12%).',
            'جدول أسعار تجريبي — ليس عرض سعر ملزماً. جميع بنود الشحن تقديرية (نطاق −8% / +12%).'),
        t('Duties and taxes are estimated from the HS chapter and a per-country table.',
            'الجمارك والضرائب مقدّرة حسب فصل HS وجدول الدولة.'),
        t('Chargeable weight: LCL 1 m³ = 1000 kg, air 1 m³ = 167 kg.',
            'الوزن المحتسب: الشحن المجمّع 1 م³ = 1000 كغم، الجوي 1 م³ = 167 كغم.'),
        t('Supplier incoterm ${inc.json}: stages already in the supplier price show as zero.',
            'شرط تسليم المورد ${inc.json}: البنود المشمولة في سعر المورد تظهر بقيمة صفر.'),
        t('FX: 1 USD = ${fx.toStringAsFixed(4)} $cur (mock rate).',
            'سعر الصرف: 1 USD = ${fx.toStringAsFixed(4)} $cur (سعر تجريبي).'),
      ],
    );
  }

  static Money _m(double v, String cur) =>
      Money(amount: (v < 0 ? 0 : v).toStringAsFixed(2), currency: cur);

  static MoneyBand _band(String cur, double base, double down, double up,
          {String? shock, String? goodsCurrency}) =>
      MoneyBand(
        low: _m(base - down, cur),
        base: _m(base, cur),
        high: _m(base + up, cur),
        shockPct: shock,
        goodsCurrency: goodsCurrency,
      );

  /// Mock "what if" ranges: freight +/-25% of the main leg, goods FX +/-5%.
  static CostSensitivity _sensitivity({
    required String cur,
    required double base,
    required double freight,
    required double goods,
    required String goodsCurrency,
    required bool ar,
  }) {
    final f = freight * 0.25;
    final x = goods * 0.05;
    return CostSensitivity(
      currency: cur,
      freight: _band(cur, base, f, f, shock: '25'),
      fx: _band(cur, base, x, x, shock: '5', goodsCurrency: goodsCurrency),
      combined: _band(cur, base, f + x, f + x),
      note: ar
          ? 'نطاقات اختبار إجهاد تجريبية وليست توقعات.'
          : 'Mock stress ranges, not forecasts.',
    );
  }

  static String _airHub(Location l) {
    final c = (l.city ?? '').toLowerCase();
    if (l.countryCode == 'IQ') {
      if (c.contains('erbil') || c.contains('أربيل') || c.contains('اربيل')) return 'Erbil Intl (EBL)';
      if (c.contains('basra') || c.contains('البصرة')) return 'Basra Intl (BSR)';
      if (c.contains('najaf') || c.contains('النجف')) return 'Najaf Intl (NJF)';
      return 'Baghdad Intl (BGW)';
    }
    return '${l.city ?? l.countryCode} airport';
  }

  static CostLine _withNote(CostLine l, String note) => CostLine(
        stage: l.stage,
        description: '${l.description}$note',
        amount: l.amount,
        estimate: false,
        source: l.source,
        fxRate: l.fxRate,
      );
}
