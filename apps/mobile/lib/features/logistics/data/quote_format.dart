import 'package:factory_finder/core/models/models.dart';

/// Pure helpers for the calculator / results screens: exact decimal input
/// handling (no binary floats on the wire), HS validation, estimate labels,
/// incoterm coverage and the share/export text.

const String _arabicIndic = '٠١٢٣٤٥٦٧٨٩';
const String _easternIndic = '۰۱۲۳۴۵۶۷۸۹';

final RegExp _plainDecimal = RegExp(r'^(\d+)(?:\.(\d+))?$');

/// Normalises user input to a plain decimal string, or null when it is empty
/// or not a number. Accepts Arabic-Indic digits, `٫` as the decimal mark,
/// `٬` / spaces / `,` as thousands separators (`1,500` = 1500) and a lone
/// comma with 1-2 digits after it as a decimal comma (`1,5` = 1.5).
/// Result has no leading zeros and no trailing fractional zeros.
String? normalizeDecimalInput(String raw) {
  final b = StringBuffer();
  for (final ch in raw.trim().split('')) {
    final a = _arabicIndic.indexOf(ch);
    final e = _easternIndic.indexOf(ch);
    if (a >= 0) {
      b.write(a);
    } else if (e >= 0) {
      b.write(e);
    } else if (ch == '٫') {
      b.write('.');
    } else if (ch == '٬' || ch == ' ' || ch == ' ') {
      // thousands separator
    } else {
      b.write(ch);
    }
  }
  var s = b.toString();
  if (s.isEmpty) return null;
  if (s.contains(',')) {
    if (s.contains('.')) {
      s = s.replaceAll(',', '');
    } else if (RegExp(r'^\d{1,3}(,\d{3})+$').hasMatch(s)) {
      s = s.replaceAll(',', '');
    } else if (RegExp(r'^\d*,\d{1,2}$').hasMatch(s)) {
      s = s.replaceFirst(',', '.');
    } else {
      return null;
    }
  }
  if (!RegExp(r'\d').hasMatch(s)) return null;
  if (s.startsWith('.')) s = '0$s';
  if (s.endsWith('.')) s = s.substring(0, s.length - 1);
  final m = _plainDecimal.firstMatch(s);
  if (m == null) return null;
  final intPart = m.group(1)!.replaceFirst(RegExp(r'^0+(?=\d)'), '');
  final frac = (m.group(2) ?? '').replaceFirst(RegExp(r'0+$'), '');
  if (intPart.length > 15 || frac.length > 8) return null;
  return frac.isEmpty ? intPart : '$intPart.$frac';
}

/// True for a normalised decimal that is exactly zero.
bool isZeroDecimal(String s) => RegExp(r'^[+-]?0*(\.0*)?$').hasMatch(s.trim());

/// Exact product of two normalised decimal strings (BigInt arithmetic).
String decimalMul(String a, String b) {
  (BigInt, int) parse(String s) {
    final dot = s.indexOf('.');
    final frac = dot < 0 ? '' : s.substring(dot + 1);
    final digits = dot < 0 ? s : s.substring(0, dot) + frac;
    return (BigInt.parse(digits.isEmpty ? '0' : digits), frac.length);
  }

  final x = parse(a);
  final y = parse(b);
  final prod = (x.$1 * y.$1).toString();
  final scale = x.$2 + y.$2;
  if (scale == 0) return prod;
  final padded = prod.padLeft(scale + 1, '0');
  final intPart = padded.substring(0, padded.length - scale);
  final frac = padded.substring(padded.length - scale).replaceFirst(RegExp(r'0+$'), '');
  return frac.isEmpty ? intPart : '$intPart.$frac';
}

/// At least two decimals, never rounded: "10" -> "10.00", "0.125" -> "0.125".
String decimalAtLeast2(String s) {
  final dot = s.indexOf('.');
  if (dot < 0) return '$s.00';
  final frac = s.substring(dot + 1);
  return frac.length >= 2 ? s : '$s${'0' * (2 - frac.length)}';
}

/// HS code check: optional, but when given it must be 6-10 digits once
/// dots, dashes and spaces are removed. [code] is the digits-only form.
({bool ok, String? code}) parseHsCode(String raw) {
  final cleaned = raw.trim();
  if (cleaned.isEmpty) return (ok: true, code: null);
  final b = StringBuffer();
  for (final ch in cleaned.split('')) {
    final a = _arabicIndic.indexOf(ch);
    if (a >= 0) {
      b.write(a);
    } else if (ch == '.' || ch == '-' || ch == ' ') {
      // separator
    } else {
      b.write(ch);
    }
  }
  final digits = b.toString();
  if (!RegExp(r'^\d{6,10}$').hasMatch(digits)) return (ok: false, code: null);
  return (ok: true, code: digits);
}

/// Stages the supplier already pays for under [incoterm] (mirrors the quote
/// engine's table): a zero line for such a stage means "included in the
/// supplier price", not "free".
bool supplierCoversStage(Incoterm incoterm, String stage) {
  switch (stage) {
    case 'origin_inland':
      return incoterm != Incoterm.exw;
    case 'origin_handling':
      return incoterm != Incoterm.exw && incoterm != Incoterm.fca;
    case 'main_leg':
      return incoterm == Incoterm.cfr ||
          incoterm == Incoterm.cif ||
          incoterm == Incoterm.dap ||
          incoterm == Incoterm.ddp;
    case 'insurance':
      return incoterm == Incoterm.cif ||
          incoterm == Incoterm.dap ||
          incoterm == Incoterm.ddp;
    case 'destination_inland':
      return incoterm == Incoterm.dap || incoterm == Incoterm.ddp;
    case 'duties':
    case 'taxes':
    case 'clearance':
      return incoterm == Incoterm.ddp;
  }
  return false;
}

enum QuoteConfidence { low, medium, high }

/// What the UI says about how trustworthy an option's numbers are.
class EstimateLabel {
  const EstimateLabel({
    required this.isEstimate,
    this.confidence,
    this.asOf,
  });

  /// False only when every line is an exact (quoted / non-estimate) amount.
  final bool isEstimate;

  /// Null = the server did not state one (shown as "not stated", never "high").
  final QuoteConfidence? confidence;

  /// `YYYY-MM` or `YYYY-MM-DD` as sent by the server.
  final String? asOf;
}

final RegExp _enLabel = RegExp(
  r'estimate,?\s*confidence\s+(low|medium|high)(?:,?\s*as of\s+(\d{4}-\d{2}(?:-\d{2})?))?',
  caseSensitive: false,
);
final RegExp _arLabel = RegExp(
  r'الثقة\s+(منخفضة|متوسطة|عالية)(?:[،,]?\s*حتى\s+(\d{4}-\d{2}(?:-\d{2})?))?',
);
final RegExp _lineLabel = RegExp(
  r'as of\s+(\d{4}-\d{2}(?:-\d{2})?),?\s*confidence\s+(low|medium|high)',
  caseSensitive: false,
);

QuoteConfidence? _conf(String s) {
  switch (s.toLowerCase()) {
    case 'low':
    case 'منخفضة':
      return QuoteConfidence.low;
    case 'medium':
    case 'متوسطة':
      return QuoteConfidence.medium;
    case 'high':
    case 'عالية':
      return QuoteConfidence.high;
  }
  return null;
}

/// Derives the label from the option's estimate warning
/// ("Estimate, confidence low, as of 2026-10: ...") and line sources.
/// When several confidences are present the LOWEST wins (never flatter the
/// quote); an unparseable server text stays "not stated".
EstimateLabel estimateLabelOf(LandedCostOption o) {
  QuoteConfidence? conf;
  String? asOf;
  void take(QuoteConfidence? c, String? d) {
    if (c != null && (conf == null || c.index < conf!.index)) conf = c;
    if (d != null && (asOf == null || d.compareTo(asOf!) > 0)) asOf = d;
  }

  for (final w in o.warnings) {
    final m = _enLabel.firstMatch(w) ?? _arLabel.firstMatch(w);
    if (m != null) take(_conf(m.group(1)!), m.group(2));
  }
  for (final l in o.lines) {
    final s = l.source;
    if (s == null) continue;
    final m = _lineLabel.firstMatch(s);
    if (m != null && l.estimate) take(_conf(m.group(2)!), m.group(1));
  }
  final anyEstimate = o.lines.any((l) => l.estimate && !l.quoted);
  final labelled = conf != null || asOf != null;
  return EstimateLabel(
    isEstimate: anyEstimate || labelled || o.lines.isEmpty,
    confidence: conf,
    asOf: asOf,
  );
}

/// Overall label of a quote: lowest confidence of all options.
EstimateLabel estimateLabelOfQuote(LandedCostQuote q) {
  QuoteConfidence? conf;
  String? asOf;
  var est = false;
  for (final o in q.options) {
    final l = estimateLabelOf(o);
    est = est || l.isEstimate;
    if (l.confidence != null && (conf == null || l.confidence!.index < conf.index)) {
      conf = l.confidence;
    }
    if (l.asOf != null && (asOf == null || l.asOf!.compareTo(asOf) > 0)) asOf = l.asOf;
  }
  return EstimateLabel(isEstimate: est || q.options.isEmpty, confidence: conf, asOf: asOf);
}

/// Plain-text export of a quote. [t] translates a key; [modeName] names a mode.
/// Always ends with the estimate disclaimer; amounts are the server's decimal
/// strings formatted without float rounding.
String buildQuoteShareText(
  LandedCostQuote quote, {
  required String Function(String key, [Map<String, String> args]) t,
  required String Function(TransportMode mode) modeName,
  Incoterm? incoterm,
}) {
  final b = StringBuffer();
  b.writeln(t('logistics.share.title'));
  final o = quote.origin;
  final d = quote.destination;
  if (o != null || d != null) {
    b.writeln('${_place(o)} > ${_place(d)}');
  }
  if (incoterm != null) {
    b.writeln(t('logistics.share.incoterm', {'i': incoterm.json}));
  }
  b.writeln(t('logistics.share.currency', {'c': quote.currency}));
  for (final opt in quote.options) {
    final label = estimateLabelOf(opt);
    b.writeln();
    b.writeln('${modeName(opt.mode)}${opt.recommended ? ' *' : ''}');
    b.writeln(
      '  ${t('logistics.results.total')}: ${opt.total.format()}'
      ' (${label.isEstimate ? t('common.estimate') : t('logistics.exact')})',
    );
    b.writeln(
      '  ${t('common.days', {'min': '${opt.transitDays.min}', 'max': '${opt.transitDays.max}'})}',
    );
    b.writeln('  ${t('logistics.confidence.label', {'c': confidenceText(t, label.confidence)})}');
    if (label.asOf != null) {
      b.writeln('  ${t('logistics.as_of', {'d': label.asOf!})}');
    }
  }
  for (final w in quote.warnings) {
    b.writeln();
    b.writeln('! $w');
  }
  b.writeln();
  b.writeln(t('logistics.share.disclaimer'));
  return b.toString().trimRight();
}

String _place(Location? l) {
  if (l == null) return '?';
  return l.city == null || l.city!.isEmpty ? l.countryCode : '${l.city}, ${l.countryCode}';
}

String confidenceText(
  String Function(String key, [Map<String, String> args]) t,
  QuoteConfidence? c,
) {
  switch (c) {
    case QuoteConfidence.low:
      return t('logistics.confidence.low');
    case QuoteConfidence.medium:
      return t('logistics.confidence.medium');
    case QuoteConfidence.high:
      return t('logistics.confidence.high');
    case null:
      return t('logistics.confidence.unknown');
  }
}
