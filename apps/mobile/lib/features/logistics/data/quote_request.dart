import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/logistics/data/quote_format.dart';

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
    this.goodsValueText,
    this.weightText,
    this.volumeText,
  });

  /// Exact decimal strings typed by the user. When set they are sent on the
  /// wire instead of the (binary float) numbers below, so no digits are lost.
  final String? goodsValueText;
  final String? weightText;
  final String? volumeText;

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

  /// Copy with the given fields replaced (the override can be cleared).
  QuoteRequest copyWith({
    String? goodsCurrency,
    String? displayCurrency,
    Incoterm? incoterm,
    Set<TransportMode>? modes,
    bool clearOverride = false,
  }) =>
      QuoteRequest(
        goodsValue: goodsValue,
        weightKg: weightKg,
        volumeM3: volumeM3,
        origin: origin,
        destination: destination,
        goodsCurrency: goodsCurrency ?? this.goodsCurrency,
        hsCode: hsCode,
        dangerousGoods: dangerousGoods,
        incoterm: incoterm ?? this.incoterm,
        displayCurrency: displayCurrency ?? this.displayCurrency,
        insurance: insurance,
        modes: modes ?? this.modes,
        freightOverride: clearOverride ? null : freightOverride,
        goodsValueText: goodsValueText,
        weightText: weightText,
        volumeText: volumeText,
      );

  /// Copy without the forwarder override.
  QuoteRequest withoutOverride() => copyWith(clearOverride: true);

  /// Body of POST /v1/quotes/landed-cost (contracts/openapi/logistics.yaml).
  Map<String, dynamic> toJson() => {
        'goods': {
          'total_value': {
            'amount': goodsValueText != null
                ? decimalAtLeast2(goodsValueText!)
                : goodsValue.toStringAsFixed(2),
            'currency': goodsCurrency,
          },
          'total_weight_kg': weightText ?? decimalString(weightKg),
          if (volumeText != null
              ? !isZeroDecimal(volumeText!)
              : volumeM3 > 0)
            'total_volume_m3': volumeText ?? decimalString(volumeM3),
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
String decimalString(double v, {int digits = 4}) {
  var s = v.toStringAsFixed(digits);
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
    this.listingId,
  });

  /// Quantity is the listing's MOQ (1 when unknown); the unit price is the
  /// middle of its price range.
  factory ListingPrefill.fromListing(Listing l) => ListingPrefill(
        listingId: l.id,
        title: l.title,
        unitPrice: (l.price.min.value + l.price.max.value) / 2,
        currency: l.price.min.currency,
        quantity: l.moq ?? 1,
        unitWeightKg: l.unitWeightKg ?? 1,
        unitVolumeM3: l.unitVolumeM3 ?? 0.01,
        incoterm: l.incoterm ?? Incoterm.fob,
        origin: l.origin ?? l.supplier.location,
        hsCode: l.hsCode,
      );

  /// Set when built from a real listing (matches the `listing_id` route query).
  final String? listingId;
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
