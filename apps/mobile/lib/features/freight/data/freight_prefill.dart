import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/freight/data/freight_decimal.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Values carried from the landed-cost results screen into the freight
/// request form. Everything is optional; the form fills the gaps.
class FreightPrefill {
  const FreightPrefill({
    this.originCountry,
    this.originPlace,
    this.destinationCountry,
    this.destinationPlace,
    this.mode,
    this.containerType,
    this.incoterm,
    this.weightKg,
    this.volumeCbm,
    this.hsCode,
    this.landedCostRef,
    this.currency,
  });

  final String? originCountry;
  final String? originPlace;
  final String? destinationCountry;
  final String? destinationPlace;

  /// sea | air | road | rail
  final String? mode;
  final String? containerType;
  final String? incoterm;

  /// Decimal strings (3 decimals max).
  final String? weightKg;
  final String? volumeCbm;
  final String? hsCode;
  final String? landedCostRef;
  final String? currency;

  /// Builds a prefill from the latest landed-cost [quote] and (when known)
  /// the calculator inputs it was computed from.
  factory FreightPrefill.fromLandedCost(LandedCostQuote quote, {QuoteRequest? inputs}) {
    // Ignore calculator inputs that belong to a different route.
    final request = inputs != null &&
            (quote.origin == null ||
                quote.origin!.countryCode == inputs.origin.countryCode) &&
            (quote.destination == null ||
                quote.destination!.countryCode == inputs.destination.countryCode)
        ? inputs
        : null;
    LandedCostOption? option;
    for (final o in quote.options) {
      if (o.recommended) option = o;
    }
    option ??= quote.options.isEmpty ? null : quote.options.first;
    final transport = option?.mode;
    final ref = RegExp(r'^[A-Za-z0-9_.:\-]{1,64}$').hasMatch(quote.id) ? quote.id : null;
    final volume = request?.volumeM3 ?? 0;
    return FreightPrefill(
      originCountry: quote.origin?.countryCode ?? request?.origin.countryCode,
      originPlace: quote.origin?.city ?? request?.origin.city,
      destinationCountry: quote.destination?.countryCode ?? request?.destination.countryCode,
      destinationPlace: quote.destination?.city ?? request?.destination.city,
      mode: transport == null ? null : freightModeOf(transport),
      containerType: transport == null ? null : containerTypeOf(transport),
      incoterm: request?.incoterm.json,
      weightKg: request == null || request.weightKg <= 0
          ? null
          : FreightDecimal.fromDouble(request.weightKg, 3),
      volumeCbm: volume > 0 ? FreightDecimal.fromDouble(volume, 3) : null,
      hsCode: request?.hsCode,
      landedCostRef: ref,
    );
  }
}

/// Landed-cost transport mode -> freight marketplace mode.
String freightModeOf(TransportMode m) {
  switch (m) {
    case TransportMode.seaLcl:
    case TransportMode.seaFcl20:
    case TransportMode.seaFcl40:
    case TransportMode.seaFcl40hc:
      return 'sea';
    case TransportMode.air:
      return 'air';
    case TransportMode.rail:
      return 'rail';
    case TransportMode.road:
      return 'road';
  }
}

String? containerTypeOf(TransportMode m) {
  switch (m) {
    case TransportMode.seaLcl:
      return 'LCL';
    case TransportMode.seaFcl20:
      return '20GP';
    case TransportMode.seaFcl40:
      return '40GP';
    case TransportMode.seaFcl40hc:
      return '40HC';
    default:
      return null;
  }
}

/// Set by the results screen right before opening the request form.
final freightPrefillProvider = StateProvider<FreightPrefill?>((ref) => null);

/// Calculator inputs of the latest quote (set by the calculator screen) so
/// the freight request can be prefilled with weight, volume and incoterm.
final lastQuoteRequestProvider = StateProvider<QuoteRequest?>((ref) => null);
