import 'dart:math' as math;
import 'dart:ui';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/utils/number_format.dart';

/// Periods the API accepts (`days` query parameter).
const List<int> kAnalyticsPeriods = <int>[7, 30, 90];
const int kDefaultAnalyticsDays = 30;

/// Direction of a period-over-period change.
enum ChangeDirection { up, down, flat, unknown }

class ChangeInfo {
  const ChangeInfo(this.direction, this.pct);

  final ChangeDirection direction;

  /// Rounded to one decimal; null when [direction] is unknown.
  final double? pct;
}

/// Classifies [pct] (null = previous value was 0). |change| < 0.05 % is flat.
ChangeInfo classifyChange(double? pct) {
  if (pct == null || pct.isNaN || pct.isInfinite) {
    return const ChangeInfo(ChangeDirection.unknown, null);
  }
  final rounded = (pct * 10).round() / 10;
  if (rounded == 0) return const ChangeInfo(ChangeDirection.flat, 0);
  return ChangeInfo(
    rounded > 0 ? ChangeDirection.up : ChangeDirection.down,
    rounded,
  );
}

/// `+12.5%`, `-3%`, `0%`; `` for unknown. Always western digits.
String formatChange(ChangeInfo c) {
  final p = c.pct;
  if (p == null) return '';
  final abs = p.abs();
  final body = abs == abs.roundToDouble()
      ? abs.toStringAsFixed(0)
      : abs.toStringAsFixed(1);
  if (p > 0) return '+$body%';
  if (p < 0) return '-$body%';
  return '$body%';
}

/// Ratio 0..1 -> `12.5%` (one decimal, trailing .0 dropped); `-` when null.
String formatRatio(double? ratio) {
  if (ratio == null || ratio.isNaN || ratio.isInfinite) return '-';
  final pct = (ratio * 1000).round() / 10;
  return pct == pct.roundToDouble()
      ? '${pct.toStringAsFixed(0)}%'
      : '${pct.toStringAsFixed(1)}%';
}

/// Grouped integer (`12,345`).
String formatCount(int n) =>
    formatDecimalString('$n', fractionDigits: 0);

/// Funnel bar fractions 0..1 relative to the largest step.
List<double> funnelFractions(List<int> steps) {
  final top = steps.fold<int>(0, math.max);
  if (top <= 0) return List<double>.filled(steps.length, 0);
  return [for (final s in steps) (s / top).clamp(0.0, 1.0).toDouble()];
}

/// Rounds [maxValue] up to a "nice" axis maximum (1, 2, 5 x 10^n); at least 1.
int niceMax(int maxValue) {
  if (maxValue <= 1) return 1;
  final exp = math.pow(10, (math.log(maxValue) / math.ln10).floor()).toInt();
  for (final m in const [1, 2, 5, 10]) {
    if (maxValue <= m * exp) return m * exp;
  }
  return 10 * exp;
}

/// Line chart points: x evenly spaced, y zero-based against [yMax].
/// A single value is centred horizontally.
List<Offset> mapSeriesPoints(
  List<int> values,
  Size size, {
  required int yMax,
  double left = 4,
  double top = 6,
  double right = 4,
  double bottom = 6,
}) {
  if (values.isEmpty) return const [];
  final w = math.max(0.0, size.width - left - right);
  final h = math.max(0.0, size.height - top - bottom);
  final m = math.max(1, yMax);
  return [
    for (var i = 0; i < values.length; i++)
      Offset(
        left + (values.length == 1 ? 0.5 : i / (values.length - 1)) * w,
        top + (1 - (values[i].clamp(0, m)) / m) * h,
      ),
  ];
}

/// Bar rects for the same layout (bars grow from the bottom baseline).
List<Rect> mapSeriesBars(
  List<int> values,
  Size size, {
  required int yMax,
  double left = 4,
  double top = 6,
  double right = 4,
  double bottom = 6,
  double gapFraction = 0.25,
}) {
  if (values.isEmpty) return const [];
  final w = math.max(0.0, size.width - left - right);
  final h = math.max(0.0, size.height - top - bottom);
  final m = math.max(1, yMax);
  final slot = w / values.length;
  final barW = slot * (1 - gapFraction);
  return [
    for (var i = 0; i < values.length; i++)
      Rect.fromLTWH(
        left + slot * i + (slot - barW) / 2,
        top + (1 - (values[i].clamp(0, m)) / m) * h,
        barW,
        (values[i].clamp(0, m)) / m * h,
      ),
  ];
}

/// Mapping of API failures to string keys.
String analyticsErrorKey(Object error) {
  if (error is ApiException) {
    switch (error.status) {
      case 401:
        return 'ana.err.signin';
      case 403:
        return 'ana.err.supplier';
      case 404:
        return 'ana.err.not_found';
      case 422:
        return 'ana.err.bad_request';
      case 429:
        return 'ana.err.rate_limited';
    }
    if (error.code == 'supplier_required') return 'ana.err.supplier';
    if (error.code == 'timeout' || error.code == 'network_error') {
      return 'ana.err.network';
    }
  }
  return 'ana.err.generic';
}
