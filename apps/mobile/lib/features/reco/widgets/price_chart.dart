import 'package:factory_finder/features/reco/chart_math.dart';
import 'package:factory_finder/features/reco/reco_models.dart';
import 'package:flutter/material.dart';

/// Simple line chart of bucket averages. Wrapped by the caller in a
/// [Semantics] node (see PriceHistoryCard) because a painter has no text.
class PriceChartPainter extends CustomPainter {
  PriceChartPainter({
    required this.points,
    required this.lineColor,
    required this.gridColor,
    this.padding = const EdgeInsets.all(8),
  });

  final List<PricePoint> points;
  final Color lineColor;
  final Color gridColor;
  final EdgeInsets padding;

  @override
  void paint(Canvas canvas, Size size) {
    final offsets = mapChartPoints(points, size, padding: padding);
    if (offsets.isEmpty) return;

    final grid = Paint()
      ..color = gridColor
      ..strokeWidth = 1;
    for (var i = 0; i < 3; i++) {
      final y = padding.top + (size.height - padding.vertical) * i / 2;
      canvas.drawLine(Offset(padding.left, y), Offset(size.width - padding.right, y), grid);
    }

    if (offsets.length >= 2) {
      final line = Path()..moveTo(offsets.first.dx, offsets.first.dy);
      for (final o in offsets.skip(1)) {
        line.lineTo(o.dx, o.dy);
      }
      final bottom = size.height - padding.bottom;
      final fill = Path.from(line)
        ..lineTo(offsets.last.dx, bottom)
        ..lineTo(offsets.first.dx, bottom)
        ..close();
      canvas.drawPath(fill, Paint()..color = lineColor.withOpacity(0.12));
      canvas.drawPath(
        line,
        Paint()
          ..color = lineColor
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2.2
          ..strokeJoin = StrokeJoin.round
          ..strokeCap = StrokeCap.round,
      );
    }
    canvas.drawCircle(offsets.last, 4, Paint()..color = lineColor);
  }

  @override
  bool shouldRepaint(PriceChartPainter old) =>
      old.points != points ||
      old.lineColor != lineColor ||
      old.gridColor != gridColor ||
      old.padding != padding;
}
