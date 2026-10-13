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

  Map<String, dynamic> toJson() => {
        'goods_value': {'amount': goodsValue.toStringAsFixed(2), 'currency': goodsCurrency},
        'weight_kg': weightKg,
        'volume_m3': volumeM3,
        if (hsCode != null) 'hs_code': hsCode,
        'dangerous_goods': dangerousGoods,
        'origin': origin.toJson(),
        'destination': destination.toJson(),
        'incoterm': incoterm.json,
        'display_currency': displayCurrency,
        'insurance': insurance,
        'modes': modes.map((m) => m.json).toList(),
      };
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
