import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';
import 'package:factory_finder/features/requests/data/rfq_validators.dart';

const int kTitleMin = 3;
const int kTitleMax = 140;
const int kDescriptionMax = 4000;

final RegExp _plainDecimal = RegExp(r'^[0-9]{1,12}(\.[0-9]{1,6})?$');
final RegExp _nonZeroDigit = RegExp('[1-9]');
final RegExp _digitsOnly = RegExp(r'^[0-9]+$');

/// Trimmed, digits normalised (Arabic-Indic digits, comma decimal).
String cleanDecimalInput(String s) => normalizeNumberInput(s);

bool isPlainDecimal(String s) => _plainDecimal.hasMatch(s);

/// True for a plain decimal string that is greater than zero.
bool isPositiveDecimal(String s) => isPlainDecimal(s) && _nonZeroDigit.hasMatch(s);

/// Exact comparison of two plain decimal strings (no doubles). Returns a
/// negative number, zero or a positive number like [Comparable.compareTo].
int compareDecimalStrings(String a, String b) {
  String intPart(String s) {
    final i = s.indexOf('.');
    final p = i < 0 ? s : s.substring(0, i);
    final t = p.replaceFirst(RegExp(r'^0+'), '');
    return t;
  }

  String fracPart(String s) {
    final i = s.indexOf('.');
    return i < 0 ? '' : s.substring(i + 1);
  }

  final ia = intPart(a);
  final ib = intPart(b);
  if (ia.length != ib.length) return ia.length - ib.length;
  final c = ia.compareTo(ib);
  if (c != 0) return c;
  final fa = fracPart(a);
  final fb = fracPart(b);
  final n = fa.length > fb.length ? fa.length : fb.length;
  return fa.padRight(n, '0').compareTo(fb.padRight(n, '0'));
}

/// HS code digits only ("9405.42" -> "940542").
String hsDigits(String s) => normalizeNumberInput(s).replaceAll(RegExp(r'[\s.\-]'), '');

bool isValidHsCode(String s) {
  final d = hsDigits(s);
  return _digitsOnly.hasMatch(d) && d.length >= 6 && d.length <= 10;
}

/// http(s) URL with a host and no whitespace.
bool isValidImageUrl(String s) {
  final t = s.trim();
  if (t.isEmpty || t.contains(RegExp(r'\s'))) return false;
  final u = Uri.tryParse(t);
  if (u == null) return false;
  return (u.scheme == 'http' || u.scheme == 'https') && u.host.isNotEmpty;
}

/// Validates [d] against the server limits. Returns `field -> i18n key`;
/// empty when valid. Fields: title, titleAr, description, descriptionAr,
/// category, priceMin, priceMax, moq, unit, weight, volume, hs, lead, images.
Map<String, String> validateProductDraft(ProductDraft d) {
  final errors = <String, String>{};
  final title = d.title.trim();
  if (title.isEmpty) {
    errors['title'] = 'myp.err.title_required';
  } else if (title.length < kTitleMin || title.length > kTitleMax) {
    errors['title'] = 'myp.err.title_length';
  }
  final titleAr = d.titleAr.trim();
  if (titleAr.isNotEmpty && (titleAr.length < kTitleMin || titleAr.length > kTitleMax)) {
    errors['titleAr'] = 'myp.err.title_length';
  }
  if (d.description.trim().length > kDescriptionMax) {
    errors['description'] = 'myp.err.description_long';
  }
  if (d.descriptionAr.trim().length > kDescriptionMax) {
    errors['descriptionAr'] = 'myp.err.description_long';
  }
  if (d.category.trim().isEmpty) errors['category'] = 'myp.err.category_required';

  final min = cleanDecimalInput(d.priceMin);
  final max = cleanDecimalInput(d.priceMax);
  if (!isPositiveDecimal(min)) errors['priceMin'] = 'myp.err.price_invalid';
  if (!isPositiveDecimal(max)) {
    errors['priceMax'] = 'myp.err.price_invalid';
  } else if (!errors.containsKey('priceMin') && compareDecimalStrings(max, min) < 0) {
    errors['priceMax'] = 'myp.err.price_range';
  }

  final moq = int.tryParse(cleanDecimalInput(d.moq));
  if (moq == null || moq < 1) errors['moq'] = 'myp.err.moq_invalid';
  if (d.unit.trim().isEmpty) errors['unit'] = 'myp.err.unit_required';

  final w = cleanDecimalInput(d.unitWeightKg);
  if (w.isNotEmpty && !isPositiveDecimal(w)) errors['weight'] = 'myp.err.number_invalid';
  final v = cleanDecimalInput(d.unitVolumeM3);
  if (v.isNotEmpty && !isPositiveDecimal(v)) errors['volume'] = 'myp.err.number_invalid';

  if (d.hsCode.trim().isNotEmpty && !isValidHsCode(d.hsCode)) {
    errors['hs'] = 'myp.err.hs_invalid';
  }

  final lo = cleanDecimalInput(d.leadMin);
  final hi = cleanDecimalInput(d.leadMax);
  if (lo.isNotEmpty || hi.isNotEmpty) {
    final a = int.tryParse(lo);
    final b = int.tryParse(hi);
    if (a == null || b == null || a < 0 || b < a) errors['lead'] = 'myp.err.lead_invalid';
  }

  if (d.images.length > kMaxProductImages) {
    errors['images'] = 'myp.err.images_many';
  } else if (d.images.any((u) => !isValidImageUrl(u))) {
    errors['images'] = 'myp.err.image_url';
  }
  return errors;
}

/// JSON request body for POST/PUT /v1/my/listings. Call only after
/// [validateProductDraft] returned no errors. Prices stay decimal strings.
Map<String, dynamic> buildListingBody(ProductDraft d) {
  String opt(String s) => s.trim();
  final titleAr = opt(d.titleAr);
  final desc = opt(d.description);
  final descAr = opt(d.descriptionAr);
  final w = cleanDecimalInput(d.unitWeightKg);
  final v = cleanDecimalInput(d.unitVolumeM3);
  final hs = hsDigits(d.hsCode);
  final lo = cleanDecimalInput(d.leadMin);
  final hi = cleanDecimalInput(d.leadMax);
  final city = d.origin.city?.trim() ?? '';
  return <String, dynamic>{
    'kind': d.kind.json,
    'condition': d.condition.json,
    'title': d.title.trim(),
    if (titleAr.isNotEmpty) 'title_ar': titleAr,
    if (desc.isNotEmpty) 'description': desc,
    if (descAr.isNotEmpty) 'description_ar': descAr,
    'category': d.category.trim(),
    'price': <String, dynamic>{
      'min': <String, dynamic>{
        'amount': cleanDecimalInput(d.priceMin),
        'currency': d.currency,
      },
      'max': <String, dynamic>{
        'amount': cleanDecimalInput(d.priceMax),
        'currency': d.currency,
      },
    },
    'unit': d.unit.trim(),
    'moq': int.parse(cleanDecimalInput(d.moq)),
    if (d.incoterm != null) 'incoterm': d.incoterm!.json,
    if (w.isNotEmpty) 'unit_weight_kg': double.parse(w),
    if (v.isNotEmpty) 'unit_volume_m3': double.parse(v),
    if (hs.isNotEmpty) 'hs_code': hs,
    if (lo.isNotEmpty && hi.isNotEmpty)
      'lead_time_days': <String, dynamic>{'min': int.parse(lo), 'max': int.parse(hi)},
    if (d.images.isNotEmpty) 'images': d.images.map((e) => e.trim()).toList(),
    'origin': <String, dynamic>{
      'country_code': d.origin.countryCode.toUpperCase(),
      if (city.isNotEmpty) 'city': city,
    },
  };
}

/// i18n key of a friendly message for a failed my-listings call.
String myProductsErrorKey(Object error) {
  if (error is ApiException) {
    switch (error.code) {
      case 'supplier_required':
      case 'supplier_verification_required':
      case 'supplier_claim_revoked':
        return 'myp.err.supplier_required';
      case 'validation_error':
        return 'myp.err.server_validation';
      case 'listing_cap_reached':
        return 'myp.err.cap_reached';
      case 'not_published':
        return 'myp.err.not_published';
      case 'moderated':
      case 'listing_moderated':
        return 'myp.err.moderated';
      case 'trust_blocked':
        return 'myp.err.trust_blocked';
      case 'trust_unavailable':
        return 'myp.err.trust_unavailable';
      case 'rate_limited':
        return 'myp.err.rate_limited';
      case 'not_found':
        return 'myp.err.not_found';
      case 'timeout':
      case 'network_error':
        return 'myp.err.network';
    }
    switch (error.status) {
      case 403:
        return 'myp.err.supplier_required';
      case 422:
        return 'myp.err.server_validation';
      case 429:
        return 'myp.err.rate_limited';
      case 404:
        return 'myp.err.not_found';
      case 503:
        return 'myp.err.trust_unavailable';
    }
  }
  return 'myp.err.generic';
}

/// Filters [all] statuses for the chips: null = all.
const List<ListingStatus?> kStatusFilters = <ListingStatus?>[
  null,
  ListingStatus.draft,
  ListingStatus.published,
  ListingStatus.archived,
  ListingStatus.pendingReview,
  ListingStatus.hidden,
];
