import 'package:factory_finder/features/analytics/analytics_logic.dart';
import 'package:flutter/material.dart';

enum AnalyticsChartStyle { line, bars }

/// Zero-based line / bar chart of one daily series. The caller wraps the
/// [CustomPaint] in a [Semantics] node (a painter has no text of its own).
class AnalyticsChartPainter extends CustomPainter {
  AnalyticsChartPainter({
    required this.values,
    required this.yMax,
    required this.color,
    required this.gridColor,
    this.style = AnalyticsChartStyle.line,
  });

  final List<int> values;
  final int yMax;
  final Color color;
  final Color gridColor;
  final AnalyticsChartStyle style;

  @override
  void paint(Canvas canvas, Size size) {
    const top = 6.0, bottom = 6.0;
    final grid = Paint()
      ..color = gridColor
      ..strokeWidth = 1;
    for (var i = 0; i < 3; i++) {
      final y = top + (size.height - top - bottom) * i / 2;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }
    if (values.isEmpty) return;

    if (style == AnalyticsChartStyle.bars) {
      final paint = Paint()..color = color;
      for (final r in mapSeriesBars(values, size, yMax: yMax)) {
        if (r.height <= 0) continue;
        canvas.drawRRect(
          RRect.fromRectAndRadius(r, const Radius.circular(2)),
          paint,
        );
      }
      return;
    }

    final pts = mapSeriesPoints(values, size, yMax: yMax);
    if (pts.length >= 2) {
      final line = Path()..moveTo(pts.first.dx, pts.first.dy);
      for (final p in pts.skip(1)) {
        line.lineTo(p.dx, p.dy);
      }
      final base = size.height - bottom;
      final fill = Path.from(line)
        ..lineTo(pts.last.dx, base)
        ..lineTo(pts.first.dx, base)
        ..close();
      canvas.drawPath(fill, Paint()..color = color.withOpacity(0.12));
      canvas.drawPath(
        line,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.2
          ..strokeJoin = StrokeJoin.round
          ..strokeCap = StrokeCap.round,
      );
    }
    canvas.drawCircle(pts.last, 4, Paint()..color = color);
  }

  @override
  bool shouldRepaint(AnalyticsChartPainter old) =>
      old.values != values ||
      old.yMax != yMax ||
      old.color != color ||
      old.gridColor != gridColor ||
      old.style != style;
}
