import 'dart:ui';

import 'package:factory_finder/features/reco/reco_models.dart';
import 'package:flutter/painting.dart';

/// Maps price points into [size] (minus [padding]) for the line chart.
///
/// x is proportional to time (evenly spaced when all timestamps are equal),
/// y is the bucket average scaled between the lowest and highest average
/// (larger price = smaller y). A single point is centred; a flat series sits
/// in the vertical middle.
List<Offset> mapChartPoints(
  List<PricePoint> points,
  Size size, {
  EdgeInsets padding = const EdgeInsets.all(8),
}) {
  if (points.isEmpty) return const [];
  final left = padding.left;
  final top = padding.top;
  final w = (size.width - padding.horizontal).clamp(0.0, double.infinity);
  final h = (size.height - padding.vertical).clamp(0.0, double.infinity);

  final values = [for (final p in points) p.avgValue];
  var lo = values.first;
  var hi = values.first;
  for (final v in values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  final range = hi - lo;

  final t0 = points.first.t.millisecondsSinceEpoch;
  final span = points.last.t.millisecondsSinceEpoch - t0;

  final out = <Offset>[];
  for (var i = 0; i < points.length; i++) {
    final double fx;
    if (points.length == 1) {
      fx = 0.5;
    } else if (span <= 0) {
      fx = i / (points.length - 1);
    } else {
      fx = (points[i].t.millisecondsSinceEpoch - t0) / span;
    }
    final fy = range.abs() < 1e-12 ? 0.5 : (hi - values[i]) / range;
    out.add(Offset(left + fx * w, top + fy * h));
  }
  return out;
}

/// `yyyy-MM-dd` (UTC) without any locale data.
String formatChartDate(DateTime t) {
  final u = t.toUtc();
  String two(int v) => v.toString().padLeft(2, '0');
  return '${u.year}-${two(u.month)}-${two(u.day)}';
}
