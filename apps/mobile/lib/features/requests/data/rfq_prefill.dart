import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/requests/data/rfq_validators.dart';

/// Units the request form offers (kept in sync with kRfqUnits).
const List<String> _units = ['piece', 'kg', 'ton', 'set', 'm', 'line'];
const List<String> _currencies = ['USD', 'EUR', 'CNY', 'IQD'];

/// Assistant unit names that differ from the form's unit ids.
const Map<String, String> _unitAliases = {'meter': 'm', 'metre': 'm', 'units': 'piece', 'unit': 'piece'};

const List<String> _countryCodes = [
  'CN', 'IQ', 'TR', 'AE', 'SA', 'DE', 'IT', 'US', 'IN', 'EG', 'JO', 'KW',
];

/// Known city (English name) to its country code.
const Map<String, String> _cityCountry = {
  'baghdad': 'IQ', 'basra': 'IQ', 'erbil': 'IQ', 'sulaymaniyah': 'IQ',
  'najaf': 'IQ', 'mosul': 'IQ', 'kirkuk': 'IQ',
  'istanbul': 'TR', 'ankara': 'TR', 'mersin': 'TR',
  'dubai': 'AE', 'abu dhabi': 'AE', 'sharjah': 'AE',
  'riyadh': 'SA', 'jeddah': 'SA', 'amman': 'JO', 'cairo': 'EG',
};

/// Optional values to seed the new-request form with. Every field is only a
/// suggestion the user reviews; nothing is ever submitted from here. All
/// inputs are untrusted text, so each value is validated and dropped if bad.
class RfqPrefill {
  const RfqPrefill({
    this.title,
    this.quantity,
    this.unit,
    this.targetPrice,
    this.currency,
    this.destination,
  });

  final String? title;
  final String? quantity;
  final String? unit;
  final String? targetPrice;
  final String? currency;
  final Location? destination;

  bool get isEmpty =>
      title == null &&
      quantity == null &&
      unit == null &&
      targetPrice == null &&
      currency == null &&
      destination == null;

  static const int maxTitleLength = 120;

  static String? _title(String? v) {
    final t = (v ?? '').trim();
    if (validateRfqTitle(t) != null) return null;
    return t.length > maxTitleLength ? t.substring(0, maxTitleLength) : t;
  }

  static String? _number(String? v) {
    final t = normalizeNumberInput(v ?? '');
    if (t.isEmpty || t.length > 20) return null;
    return validateRfqQuantity(t) == null ? t : null;
  }

  static String? _unit(String? v) {
    final t = (v ?? '').trim().toLowerCase();
    final u = _unitAliases[t] ?? t;
    return _units.contains(u) ? u : null;
  }

  /// Country code (and city when the name is a known city) from a display name
  /// in English or Arabic, e.g. "Baghdad", "بغداد", "Iraq". Null when unknown.
  static Location? parseDestination(String? name) {
    final n = (name ?? '').trim();
    if (n.isEmpty) return null;
    final lower = n.toLowerCase();
    for (final lang in const ['en', 'ar']) {
      for (final cc in _countryCodes) {
        if (AppStrings.lookup(lang, 'country.$cc').toLowerCase() == lower) {
          return Location(countryCode: cc);
        }
      }
      for (final e in _cityCountry.entries) {
        final city = _cityKey(e.key);
        if (AppStrings.lookup(lang, 'city.$city').toLowerCase() == lower) {
          return Location(countryCode: e.value, city: city);
        }
      }
    }
    return null;
  }

  /// Structured destination from `prefill_destination_cc` (ISO code) and the
  /// optional English `prefill_destination_city`. Null when the code is not
  /// a supported country, so the caller can fall back to the display name.
  static Location? _structuredDestination(String? cc, String? city) {
    final code = (cc ?? '').trim().toUpperCase();
    if (!_countryCodes.contains(code)) return null;
    final c = (city ?? '').trim();
    return Location(
      countryCode: code,
      city: (c.isEmpty || c.length > 60) ? null : c,
    );
  }

  /// `city.<Name>` keys use capitalised words ("Abu Dhabi").
  static String _cityKey(String lower) => lower
      .split(' ')
      .map((w) => w.isEmpty ? w : '${w[0].toUpperCase()}${w.substring(1)}')
      .join(' ');

  /// From assistant card refs (`prefill_product`, `prefill_quantity`,
  /// `prefill_unit`, `prefill_destination_cc`, `prefill_destination_city`,
  /// `prefill_destination`, `prefill_target_price`). Structured destination
  /// refs win over the display name. Units the form lacks (container, liter)
  /// have no exact equivalent and are dropped by [_unit].
  factory RfqPrefill.fromRefs(Map<String, String> refs) {
    String? amount;
    String? currency;
    final price = refs['prefill_target_price'];
    if (price != null) {
      final parts = price.trim().split(RegExp(r'\s+'));
      if (parts.length == 2) {
        final cur = parts[1].toUpperCase();
        if (_currencies.contains(cur)) {
          amount = _number(parts[0]);
          if (amount != null) currency = cur;
        }
      }
    }
    return RfqPrefill(
      title: _title(refs['prefill_product']),
      quantity: _number(refs['prefill_quantity']),
      unit: _unit(refs['prefill_unit']),
      targetPrice: amount,
      currency: currency,
      destination: _structuredDestination(
            refs['prefill_destination_cc'],
            refs['prefill_destination_city'],
          ) ??
          parseDestination(refs['prefill_destination']),
    );
  }

  /// Query parameters for `/requests/new` (only non-null fields).
  Map<String, String> toQuery() => {
        if (title != null) 'title': title!,
        if (quantity != null) 'qty': quantity!,
        if (unit != null) 'unit': unit!,
        if (targetPrice != null) 'price': targetPrice!,
        if (currency != null) 'currency': currency!,
        if (destination != null) 'dest': destination!.countryCode,
        if (destination?.city != null) 'city': destination!.city!,
      };

  /// Parses and re-validates query parameters (the URL is untrusted too).
  factory RfqPrefill.fromQuery(Map<String, String> q) {
    final cur = (q['currency'] ?? '').toUpperCase();
    final dest = (q['dest'] ?? '').toUpperCase();
    final city = q['city'];
    return RfqPrefill(
      title: _title(q['title']),
      quantity: _number(q['qty']),
      unit: _unit(q['unit']),
      targetPrice: _number(q['price']),
      currency: _currencies.contains(cur) ? cur : null,
      destination: _countryCodes.contains(dest)
          ? Location(
              countryCode: dest,
              city: (city == null || city.isEmpty || city.length > 60) ? null : city,
            )
          : null,
    );
  }
}
