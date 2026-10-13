/// Currencies offered in the FX screen.
const List<String> kFxCurrencies = [
  'USD', 'EUR', 'CNY', 'IQD', 'TRY', 'AED', 'SAR', 'GBP', 'IRR',
];

double _num(dynamic v) {
  if (v is num) return v.toDouble();
  return double.tryParse(v?.toString() ?? '') ?? 0;
}

/// GET /v1/fx/rates: rates per 1 unit of [base] (decimal strings).
class FxRates {
  const FxRates({
    required this.base,
    required this.rates,
    this.timestamp,
    this.source = '',
  });

  final String base;
  final Map<String, String> rates;
  final DateTime? timestamp;
  final String source;

  factory FxRates.fromJson(Map<String, dynamic> json) {
    final raw = json['rates'];
    final rates = <String, String>{};
    if (raw is Map) {
      raw.forEach((k, v) => rates[k.toString()] = v.toString());
    }
    return FxRates(
      base: (json['base'] ?? 'USD').toString(),
      rates: rates,
      timestamp: DateTime.tryParse((json['timestamp'] ?? '').toString()),
      source: (json['source'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'base': base,
        'timestamp': timestamp?.toUtc().toIso8601String(),
        'source': source,
        'rates': rates,
      };

  double rateOf(String code) => code == base ? 1 : _num(rates[code]);
}

/// POST /v1/fx/convert response.
class ConvertResult {
  const ConvertResult({
    required this.amount,
    required this.currency,
    required this.rate,
    required this.from,
    required this.to,
    this.timestamp,
    this.source = '',
  });

  final String amount;
  final String currency;
  final String rate;
  final String from;
  final String to;
  final DateTime? timestamp;
  final String source;

  factory ConvertResult.fromJson(Map<String, dynamic> json) {
    final money = json['amount'];
    final m = money is Map ? money : const {};
    return ConvertResult(
      amount: (m['amount'] ?? '0').toString(),
      currency: (m['currency'] ?? json['to'] ?? '').toString(),
      rate: (json['rate'] ?? '0').toString(),
      from: (json['from'] ?? '').toString(),
      to: (json['to'] ?? '').toString(),
      timestamp: DateTime.tryParse((json['timestamp'] ?? '').toString()),
      source: (json['source'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'amount': {'amount': amount, 'currency': currency},
        'rate': rate,
        'from': from,
        'to': to,
        'timestamp': timestamp?.toUtc().toIso8601String(),
        'source': source,
      };
}

/// Cross rate: units of `to` per 1 unit of `from`, given rates quoted
/// against a common base (rate per 1 base).
double crossRate(double rateFrom, double rateTo) =>
    rateFrom == 0 ? 0 : rateTo / rateFrom;

double convertAmount(double amount, double rateFrom, double rateTo) =>
    amount * crossRate(rateFrom, rateTo);

/// Compact number formatting (no intl dependency): grouping + adaptive decimals.
String formatFx(double v) {
  if (v.isNaN || v.isInfinite) return '-';
  final decimals = v.abs() >= 100 ? 2 : (v.abs() >= 1 ? 4 : 6);
  final s = v.toStringAsFixed(decimals);
  final parts = s.split('.');
  final intPart = parts[0];
  final buf = StringBuffer();
  for (var i = 0; i < intPart.length; i++) {
    final fromEnd = intPart.length - i;
    buf.write(intPart[i]);
    if (fromEnd > 1 && fromEnd % 3 == 1 && intPart[i] != '-') buf.write(',');
  }
  var frac = parts.length > 1 ? parts[1] : '';
  frac = frac.replaceFirst(RegExp(r'0+$'), '');
  return frac.isEmpty ? buf.toString() : '${buf.toString()}.$frac';
}

String formatStamp(DateTime? t) {
  if (t == null) return '-';
  final u = t.toUtc();
  String p(int n) => n.toString().padLeft(2, '0');
  return '${u.year}-${p(u.month)}-${p(u.day)} ${p(u.hour)}:${p(u.minute)} UTC';
}
