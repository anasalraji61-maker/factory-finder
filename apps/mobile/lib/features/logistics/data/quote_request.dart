import 'package:factory_finder/core/models/models.dart';

/// Inputs of the landed-cost calculator form.
class QuoteRequest {
  const QuoteRequest({
    required this.goodsValue,
    required this.weightKg,
    required this.volumeM3,
    required this.origin,
    required this.destination,
    this.goodsCurrency = 'USD',
    this.hsCode,
    this.dangerousGoods = false,
    this.incoterm = Incoterm.fob,
    this.displayCurrency = 'USD',
    this.insurance = true,
    this.modes = const {},
    this.freightOverride,
  });

  /// Value of the goods in [goodsCurrency].
  final double goodsValue;
  final String goodsCurrency;
  final double weightKg;
  final double volumeM3;
  final String? hsCode;
  final bool dangerousGoods;
  final Location origin;
  final Location destination;
  final Incoterm incoterm;
  final String displayCurrency;
  final bool insurance;

  /// Empty = consider every mode.
  final Set<TransportMode> modes;

  /// Optional awarded forwarder quote used as the exact main-leg price.
  final FreightOverride? freightOverride;

  /// Copy without the forwarder override.
  QuoteRequest withoutOverride() => QuoteRequest(
        goodsValue: goodsValue,
        weightKg: weightKg,
        volumeM3: volumeM3,
        origin: origin,
        destination: destination,
        goodsCurrency: goodsCurrency,
        hsCode: hsCode,
        dangerousGoods: dangerousGoods,
        incoterm: incoterm,
        displayCurrency: displayCurrency,
        insurance: insurance,
        modes: modes,
      );

  /// Body of POST /v1/quotes/landed-cost (contracts/openapi/logistics.yaml).
  Map<String, dynamic> toJson() => {
        'goods': {
          'total_value': {
            'amount': goodsValue.toStringAsFixed(2),
            'currency': goodsCurrency,
          },
          'total_weight_kg': decimalString(weightKg),
          if (volumeM3 > 0) 'total_volume_m3': decimalString(volumeM3),
          if (hsCode != null && hsCode!.isNotEmpty) 'hs_code': hsCode,
          'dangerous_goods': dangerousGoods,
        },
        'origin': origin.toJson(),
        'destination': destination.toJson(),
        'supplier_incoterm': incoterm.json,
        'display_currency': displayCurrency,
        'insurance': insurance,
        'modes': modes.map((m) => m.json).toList(),
        if (freightOverride != null) 'freight_override': freightOverride!.toJson(),
        if (freightOverride?.modeFamily != null)
          'mode_family': freightOverride!.modeFamily,
      };
}

/// Calculator starting point handed over from the awarded freight quote screen.
class CalculatorSeed {
  const CalculatorSeed({
    required this.origin,
    required this.destination,
    required this.freightOverride,
  });

  final Location origin;
  final Location destination;
  final FreightOverride freightOverride;
}

/// An awarded forwarder quote as returned by freight
/// GET /v1/freight/quotes/{id}/landed-cost-input; passed unchanged as
/// `freight_override` to POST /v1/quotes/landed-cost.
class FreightOverride {
  const FreightOverride({
    required this.amount,
    required this.currency,
    required this.quoteId,
    required this.validUntil,
    this.modeFamily,
    this.source = 'forwarder_quote',
  });

  /// Exact decimal string.
  final String amount;
  final String currency;
  final String quoteId;
  final DateTime validUntil;

  /// sea | air | rail | road (optional).
  final String? modeFamily;
  final String source;

  factory FreightOverride.fromJson(Map<String, dynamic> j) => FreightOverride(
        amount: (j['amount'] ?? '0').toString(),
        currency: (j['currency'] as String?) ?? 'USD',
        quoteId: (j['quote_id'] ?? '').toString(),
        validUntil: DateTime.tryParse((j['valid_until'] ?? '').toString()) ??
            DateTime.fromMillisecondsSinceEpoch(0, isUtc: true),
        modeFamily: j['mode_family'] as String?,
        source: (j['source'] as String?) ?? 'forwarder_quote',
      );

  Map<String, dynamic> toJson() => {
        'amount': amount,
        'currency': currency,
        'source': source,
        'quote_id': quoteId,
        'valid_until': validUntil.toUtc().toIso8601String(),
        if (modeFamily != null) 'mode_family': modeFamily,
      };
}

/// Plain decimal string (no exponent, no trailing zeros): 12.5 -> "12.5".
String decimalString(double v) {
  var s = v.toStringAsFixed(4);
  if (s.contains('.')) {
    s = s.replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '');
  }
  return s.isEmpty ? '0' : s;
}

/// Fixture used to prefill the calculator from a listing in mock mode
/// (features-b owns its own copy; see AGENTS.md cross-feature rules).
class ListingPrefill {
  const ListingPrefill({
    required this.title,
    required this.unitPrice,
    required this.currency,
    required this.quantity,
    required this.unitWeightKg,
    required this.unitVolumeM3,
    required this.incoterm,
    required this.origin,
    this.hsCode,
  });

  final String title;
  final double unitPrice;
  final String currency;
  final int quantity;
  final double unitWeightKg;
  final double unitVolumeM3;
  final Incoterm incoterm;
  final Location origin;
  final String? hsCode;
}
