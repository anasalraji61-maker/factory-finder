import 'package:factory_finder/core/models/models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

enum CompareToggle { added, removed, full }

/// Listings the user picked to compare (max [maxItems]).
class CompareNotifier extends StateNotifier<List<Listing>> {
  CompareNotifier() : super(const <Listing>[]);

  static const int maxItems = 3;

  bool contains(String id) => state.any((l) => l.id == id);

  CompareToggle toggle(Listing l) {
    if (contains(l.id)) {
      state = [
        for (final x in state)
          if (x.id != l.id) x,
      ];
      return CompareToggle.removed;
    }
    if (state.length >= maxItems) return CompareToggle.full;
    state = [...state, l];
    return CompareToggle.added;
  }

  void remove(String id) {
    state = [
      for (final x in state)
        if (x.id != id) x,
    ];
  }

  void clear() => state = const <Listing>[];
}

final compareProvider = StateNotifierProvider<CompareNotifier, List<Listing>>(
  (ref) => CompareNotifier(),
);

/// Midpoint of a price range (single currency).
double rangeMid(MoneyRange r) => (r.min.value + r.max.value) / 2;

/// Index of the smallest value, or null when fewer than 2 values are present
/// or the minimum is tied. [values] may contain nulls (not comparable).
int? bestLowIndex(List<double?> values) => _bestIndex(values, low: true);

/// Index of the largest value (same rules as [bestLowIndex]).
int? bestHighIndex(List<double?> values) => _bestIndex(values, low: false);

int? _bestIndex(List<double?> values, {required bool low}) {
  var count = 0;
  int? best;
  var tied = false;
  for (var i = 0; i < values.length; i++) {
    final v = values[i];
    if (v == null) continue;
    count++;
    if (best == null) {
      best = i;
      continue;
    }
    final b = values[best]!;
    if (v == b) {
      tied = true;
    } else if (low ? v < b : v > b) {
      best = i;
      tied = false;
    }
  }
  if (count < 2 || tied) return null;
  return best;
}

/// Price midpoints per listing, or all-null when currencies differ (not comparable).
List<double?> comparablePrices(List<Listing> items) {
  if (items.isEmpty) return const <double?>[];
  final cur = items.first.price.min.currency;
  final same = items.every((l) => l.price.min.currency == cur);
  return [for (final l in items) same ? rangeMid(l.price) : null];
}

/// Landed cost for one listing at its MOQ quantity.
class CompareLanded {
  const CompareLanded({
    required this.total,
    required this.quantity,
    required this.transitDays,
  });

  /// Estimated total range (display currency).
  final MoneyRange total;
  final int quantity;
  final DayRange transitDays;

  double get perUnitMid => quantity <= 0 ? rangeMid(total) : rangeMid(total) / quantity;
}

/// Picks the recommended option, else the cheapest by range midpoint.
LandedCostOption? pickLandedOption(LandedCostQuote quote) {
  if (quote.options.isEmpty) return null;
  for (final o in quote.options) {
    if (o.recommended) return o;
  }
  var best = quote.options.first;
  for (final o in quote.options) {
    if (rangeMid(o.total) < rangeMid(best.total)) best = o;
  }
  return best;
}
