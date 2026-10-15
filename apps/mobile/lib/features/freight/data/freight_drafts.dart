import 'package:factory_finder/features/freight/data/freight_decimal.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';

/// Client-side validators. Each returns an i18n key (or null when valid) so
/// the same rules run in forms and in unit tests.
class FreightValidators {
  FreightValidators._();

  static String? text(String raw, {required int min, required int max, required String key}) {
    final n = raw.trim().length;
    return n < min || n > max ? key : null;
  }

  static String? place(String raw) => text(raw, min: 2, max: 80, key: 'freight.v.place');
  static String? cargo(String raw) => text(raw, min: 3, max: 500, key: 'freight.v.cargo');
  static String? company(String raw) => text(raw, min: 2, max: 120, key: 'freight.v.company');

  /// Positive decimal with at most [scale] decimals; empty allowed when
  /// [required] is false.
  static String? decimal(String raw, int scale, {bool required = true}) {
    if (raw.trim().isEmpty) return required ? 'freight.v.number' : null;
    final u = FreightDecimal.parseScaled(raw, scale);
    if (u == null || u <= 0) return 'freight.v.number_scale_$scale';
    return null;
  }

  /// weight_kg or volume_cbm must be present; those present must be valid.
  static String? weightOrVolume(String weight, String volume) {
    if (weight.trim().isEmpty && volume.trim().isEmpty) {
      return 'freight.v.weight_or_volume';
    }
    return decimal(weight, 3, required: false) ?? decimal(volume, 3, required: false);
  }

  /// Weight field: its own error first, then the either-or rule.
  static String? weightField(String weight, String volume) =>
      decimal(weight, 3, required: false) ?? _eitherOr(weight, volume);

  /// Volume field: its own error first, then the either-or rule.
  static String? volumeField(String weight, String volume) =>
      decimal(volume, 3, required: false) ?? _eitherOr(weight, volume);

  static String? _eitherOr(String weight, String volume) =>
      weight.trim().isEmpty && volume.trim().isEmpty
          ? 'freight.v.weight_or_volume'
          : null;

  /// 4-10 digits, dots allowed. Empty is fine.
  static String? hs(String raw) {
    final s = raw.trim();
    if (s.isEmpty) return null;
    if (!RegExp(r'^[0-9.]+$').hasMatch(s)) return 'freight.v.hs';
    final digits = s.replaceAll('.', '').length;
    return digits < 4 || digits > 10 ? 'freight.v.hs' : null;
  }

  static String? currency(String raw) =>
      RegExp(r'^[A-Z]{3}$').hasMatch(raw.trim()) ? null : 'freight.v.currency';

  /// today .. +365 days (UTC).
  static String? readyDate(DateTime date, DateTime now) {
    final today = DateTime.utc(now.toUtc().year, now.toUtc().month, now.toUtc().day);
    final d = DateTime.utc(date.year, date.month, date.day);
    if (d.isBefore(today) || d.isAfter(today.add(const Duration(days: 365)))) {
      return 'freight.v.ready_date';
    }
    return null;
  }

  static String? intRange(String raw, int min, int max, String key) {
    final n = int.tryParse(FreightDecimal.normalize(raw) ?? '');
    return n == null || n < min || n > max ? key : null;
  }

  /// Total amount: > 0, at most 2 decimals.
  static String? amount(String raw) => decimal(raw, 2);

  /// One entry per line / comma part: 2-80 chars, at most 10 entries.
  static String? listItems(List<String> items, {int max = 10, int minLen = 2, int maxLen = 80}) {
    if (items.length > max) return 'freight.v.list_too_long';
    for (final i in items) {
      if (i.length < minLen || i.length > maxLen) return 'freight.v.list_item';
    }
    return null;
  }
}

String _date(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

String formatIsoDate(DateTime d) => _date(d);

/// Body of POST /v1/freight/requests.
class RequestDraft {
  const RequestDraft({
    required this.originCountry,
    required this.originPlace,
    required this.destinationCountry,
    required this.destinationPlace,
    required this.cargoDescription,
    this.hsCode = '',
    this.weightKg = '',
    this.volumeCbm = '',
    required this.mode,
    this.containerType,
    this.containerCount,
    required this.incoterm,
    required this.readyDate,
    this.currency = 'USD',
    this.quoteDeadlineDays = 14,
    this.landedCostRef,
  });

  final String originCountry;
  final String originPlace;
  final String destinationCountry;
  final String destinationPlace;
  final String cargoDescription;
  final String hsCode;
  final String weightKg;
  final String volumeCbm;
  final String mode;
  final String? containerType;
  final int? containerCount;
  final String incoterm;
  final DateTime readyDate;
  final String currency;
  final int quoteDeadlineDays;
  final String? landedCostRef;

  Map<String, dynamic> toJson() {
    final w = FreightDecimal.canonical(weightKg, 3);
    final v = FreightDecimal.canonical(volumeCbm, 3);
    final hasContainer = (mode == 'sea' || mode == 'rail') && containerType != null;
    final hs = hsCode.trim();
    return {
      'origin_country': originCountry,
      'origin_place': originPlace.trim(),
      'destination_country': destinationCountry,
      'destination_place': destinationPlace.trim(),
      'cargo_description': cargoDescription.trim(),
      if (hs.isNotEmpty) 'hs_code': hs,
      if (w != null) 'weight_kg': w,
      if (v != null) 'volume_cbm': v,
      'mode': mode,
      if (hasContainer) 'container_type': containerType,
      if (hasContainer && containerCount != null) 'container_count': containerCount,
      'incoterm': incoterm,
      'ready_date': _date(readyDate),
      'currency': currency,
      'quote_deadline_days': quoteDeadlineDays,
      if (landedCostRef != null && landedCostRef!.isNotEmpty)
        'landed_cost_ref': landedCostRef,
    };
  }

  /// First validation error key, or null when the draft can be sent.
  String? validate(DateTime now) =>
      FreightValidators.place(originPlace) ??
      FreightValidators.place(destinationPlace) ??
      FreightValidators.cargo(cargoDescription) ??
      FreightValidators.hs(hsCode) ??
      FreightValidators.weightOrVolume(weightKg, volumeCbm) ??
      FreightValidators.currency(currency) ??
      FreightValidators.readyDate(readyDate, now);
}

/// Body of POST /v1/freight/applications.
class ApplicationDraft {
  const ApplicationDraft({
    required this.companyName,
    required this.countryCode,
    this.description = '',
    required this.lanes,
    required this.modes,
    required this.incoterms,
    this.certifications = const [],
  });

  final String companyName;
  final String countryCode;
  final String description;
  final List<Lane> lanes;
  final List<String> modes;
  final List<String> incoterms;
  final List<String> certifications;

  Map<String, dynamic> toJson() => {
        'company_name': companyName.trim(),
        'country_code': countryCode,
        if (description.trim().isNotEmpty) 'description': description.trim(),
        'lanes': [for (final l in lanes) l.toJson()],
        'modes': modes,
        'incoterms': incoterms,
        'certifications': certifications,
      };

  String? validate() {
    final c = FreightValidators.company(companyName);
    if (c != null) return c;
    if (lanes.isEmpty || lanes.length > 50) return 'freight.v.lanes';
    if (modes.isEmpty) return 'freight.v.modes';
    if (incoterms.isEmpty) return 'freight.v.incoterms';
    if (certifications.length > 10 ||
        certifications.any((e) => e.length < 2 || e.length > 40)) {
      return 'freight.v.certs';
    }
    if (description.trim().length > 1000) return 'freight.v.description';
    return null;
  }
}

/// Body of POST /v1/freight/requests/{id}/quotes and PUT /v1/freight/quotes/{id}.
/// The currency is fixed to the request currency by the caller.
class QuoteDraft {
  const QuoteDraft({
    required this.amount,
    required this.currency,
    required this.transitDays,
    this.validDays = 14,
    this.inclusions = const [],
    this.exclusions = const [],
    this.breakdown = const [],
    this.terms = '',
  });

  /// User text; canonicalised on send.
  final String amount;
  final String currency;
  final int transitDays;
  final int validDays;
  final List<String> inclusions;
  final List<String> exclusions;
  final List<QuoteLine> breakdown;
  final String terms;

  /// Sum of the breakdown lines in minor units, or null when a line is invalid.
  int? get breakdownMinor =>
      FreightDecimal.sumScaled(breakdown.map((l) => l.amount), 2);

  /// First validation error key, or null. Enforces breakdown == total exactly.
  String? validate() {
    final a = FreightValidators.amount(amount);
    if (a != null) return a;
    if (transitDays < 1 || transitDays > 365) return 'freight.v.transit';
    if (validDays < 1 || validDays > 90) return 'freight.v.valid_days';
    final inc = FreightValidators.listItems(inclusions);
    if (inc != null) return inc;
    final exc = FreightValidators.listItems(exclusions);
    if (exc != null) return exc;
    if (terms.trim().length > 1000) return 'freight.v.terms';
    if (breakdown.length > 10) return 'freight.v.list_too_long';
    for (final l in breakdown) {
      if (l.label.trim().length < 2 || l.label.trim().length > 60) {
        return 'freight.v.line_label';
      }
      final u = FreightDecimal.parseScaled(l.amount, 2);
      if (u == null || u <= 0) return 'freight.v.line_amount';
    }
    if (breakdown.isNotEmpty &&
        breakdownMinor != FreightDecimal.parseScaled(amount, 2)) {
      return 'freight.v.breakdown_mismatch';
    }
    return null;
  }

  Map<String, dynamic> toJson() => {
        'amount': FreightDecimal.canonical(amount, 2) ?? amount,
        'currency': currency,
        'transit_days': transitDays,
        'valid_days': validDays,
        'inclusions': inclusions,
        'exclusions': exclusions,
        'breakdown': [
          for (final l in breakdown)
            {
              'label': l.label.trim(),
              'amount': FreightDecimal.canonical(l.amount, 2) ?? l.amount,
            },
        ],
        'terms': terms.trim().isEmpty ? null : terms.trim(),
      };
}
