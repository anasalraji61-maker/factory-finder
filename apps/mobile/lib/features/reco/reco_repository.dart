import 'dart:async';
import 'dart:math' as math;

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/discover/data/mock_catalog.dart';
import 'package:factory_finder/features/reco/recently_viewed.dart';
import 'package:factory_finder/features/reco/reco_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class RecoRepository {
  /// GET /v1/listings/{id}/price-history
  Future<PriceHistory> priceHistory(String listingId, {int days = 90, PriceBucket? bucket});

  /// GET /v1/listings/{id}/similar
  Future<RecoPage> similar(String listingId, {int limit = 10});

  /// GET /v1/recommendations. [refs] are the client's own recently viewed ids
  /// (most recent first); nothing is stored server-side.
  Future<RecoPage> recommendations({
    List<String> refs = const [],
    String? country,
    int limit = 20,
  });
}

class LiveRecoRepository implements RecoRepository {
  LiveRecoRepository(this._api);
  final ApiClient _api;

  @override
  Future<PriceHistory> priceHistory(String listingId, {int days = 90, PriceBucket? bucket}) async {
    final json = await _api.get(
      '/v1/listings/${Uri.encodeComponent(listingId)}/price-history',
      query: {'days': days, 'bucket': (bucket ?? bucketForDays(days)).name},
    );
    return PriceHistory.fromJson(Map<String, dynamic>.from(json as Map));
  }

  @override
  Future<RecoPage> similar(String listingId, {int limit = 10}) async {
    final json = await _api.get(
      '/v1/listings/${Uri.encodeComponent(listingId)}/similar',
      query: {'limit': limit},
    );
    return RecoPage.fromJson(Map<String, dynamic>.from(json as Map));
  }

  @override
  Future<RecoPage> recommendations({
    List<String> refs = const [],
    String? country,
    int limit = 20,
  }) async {
    final ids = refs.take(kRecentlyViewedCap).toList();
    final json = await _api.get('/v1/recommendations', query: {
      if (ids.isNotEmpty) 'ref': ids.join(','),
      if (country != null && country.length == 2) 'country': country.toUpperCase(),
      'limit': limit,
    });
    return RecoPage.fromJson(Map<String, dynamic>.from(json as Map));
  }
}

int _seed(String id) {
  var h = 17;
  for (final c in id.codeUnits) {
    h = (h * 31 + c) & 0x7fffffff;
  }
  return h;
}

String _money2(double v) => v.toStringAsFixed(2);

/// Deterministic offline data built on the mock catalog (no timers, so tests
/// never wait on it). Dates follow [clock]; values depend only on the ids.
class MockRecoRepository implements RecoRepository {
  MockRecoRepository({DateTime Function()? clock}) : _clock = clock ?? DateTime.now;

  final DateTime Function() _clock;

  Listing _find(String id) => mockListings.firstWhere(
        (l) => l.id == id,
        orElse: () => throw ApiException(
          status: 404,
          code: 'not_found',
          message: 'Listing $id not found',
        ),
      );

  @override
  Future<PriceHistory> priceHistory(String listingId, {int days = 90, PriceBucket? bucket}) async {
    final l = _find(listingId);
    final b = bucket ?? bucketForDays(days);
    final stepDays = b == PriceBucket.day ? 1 : (b == PriceBucket.week ? 7 : 30);
    final count = math.max(1, (days / stepDays).ceil());
    final now = _clock().toUtc();
    final end = DateTime.utc(now.year, now.month, now.day);
    final seed = _seed(listingId);
    final phase = (seed % 628) / 100;
    final drift = ((seed % 3) - 1) * 0.12;
    var base = l.price.min.value;
    if (base <= 0) base = 1;

    final points = <PricePoint>[];
    for (var i = 0; i < count; i++) {
      final v = base *
          (1 +
              0.06 * math.sin(i * 0.45 + phase) +
              0.03 * math.sin(i * 0.13 + phase * 2) +
              drift * (i / math.max(1, count - 1) - 0.5));
      points.add(PricePoint(
        t: end.subtract(Duration(days: stepDays * (count - 1 - i))),
        avg: _money2(v),
        min: _money2(v * 0.985),
        max: _money2(v * 1.015),
        n: 1 + (i + seed) % 3,
      ));
    }
    return _assemble(listingId, l.price.min.currency, l.unit, days, b, points);
  }

  PriceHistory _assemble(
    String listingId,
    String currency,
    String unit,
    int days,
    PriceBucket bucket,
    List<PricePoint> points,
  ) {
    if (points.length < 2) {
      return PriceHistory(
        listingId: listingId,
        currency: currency,
        unit: unit,
        days: days,
        bucket: bucket,
        synthetic: true,
        points: points,
        trend: const PriceTrend(direction: PriceDirection.flat, insufficientData: true),
      );
    }
    final avgs = [for (final p in points) p.avgValue];
    final mins = [for (final p in points) double.parse(p.min)];
    final maxs = [for (final p in points) double.parse(p.max)];
    final lo = mins.reduce(math.min);
    final hi = maxs.reduce(math.max);
    final mean = avgs.reduce((a, b) => a + b) / avgs.length;
    final first = avgs.first;
    final current = avgs.last;
    final change = (current - first) / first * 100;
    final dir = change > 1
        ? PriceDirection.up
        : (change < -1 ? PriceDirection.down : PriceDirection.flat);
    final suggested = math.min(current, mean) * 0.95;
    return PriceHistory(
      listingId: listingId,
      currency: currency,
      unit: unit,
      days: days,
      bucket: bucket,
      synthetic: true,
      points: points,
      summary: PriceSummary(
        min: _money2(lo),
        max: _money2(hi),
        avg: _money2(mean),
        current: _money2(current),
        first: _money2(first),
        observations: points.fold<int>(0, (a, p) => a + p.n),
      ),
      trend: PriceTrend(
        direction: dir,
        insufficientData: false,
        changePct: change.toStringAsFixed(2),
      ),
      hints: PriceHints(
        atPeriodLow: current <= lo * 1.0005,
        atPeriodHigh: current >= hi * 0.9995,
        currentVsMinPct: ((current - lo) / lo * 100).toStringAsFixed(2),
        suggestedTarget: Money(amount: _money2(suggested), currency: currency),
      ),
    );
  }

  static const Map<String, (String, String)> _reasonText = {
    'same_category': ('نفس الفئة', 'Same category'),
    'same_condition': ('نفس الحالة', 'Same condition'),
    'similar_price': ('سعر مقارب', 'Similar price'),
    'different_supplier': ('مورّد مختلف', 'Different supplier'),
    'trusted_supplier': ('مورّد موثوق', 'Trusted supplier'),
    'because_viewed': ('لأنك شاهدت منتجات مشابهة', 'Because you viewed similar items'),
    'top_trusted': ('الأعلى موثوقية', 'Top trusted'),
  };

  RecoReason _reason(String code, {String? ref}) {
    final t = _reasonText[code] ?? (code, code);
    return RecoReason(code: code, ar: t.$1, en: t.$2, refListingId: ref);
  }

  @override
  Future<RecoPage> similar(String listingId, {int limit = 10}) async {
    final target = _find(listingId);
    final scored = <(double, RecoItem)>[];
    for (final c in mockListings) {
      if (c.id == target.id || c.kind != target.kind) continue;
      var score = 0.0;
      final reasons = <RecoReason>[];
      if (c.category != null && c.category == target.category) {
        score += 3;
        reasons.add(_reason('same_category'));
      }
      if (c.condition == target.condition) {
        score += 1;
        reasons.add(_reason('same_condition'));
      }
      final a = target.price.min.value;
      final b = c.price.min.value;
      if (a > 0 && b > 0 && c.price.min.currency == target.price.min.currency &&
          (b / a) > 0.5 && (b / a) < 2) {
        score += 1;
        reasons.add(_reason('similar_price'));
      }
      if (c.supplier.id != target.supplier.id) {
        score += 0.5;
        reasons.add(_reason('different_supplier'));
      }
      if ((c.supplier.trustScore ?? 0) >= 75) {
        score += 0.5;
        reasons.add(_reason('trusted_supplier'));
      }
      scored.add((score, RecoItem(listing: c, score: score / 6, reasons: reasons)));
    }
    scored.sort((x, y) {
      final byScore = y.$1.compareTo(x.$1);
      return byScore != 0 ? byScore : x.$2.listing.id.compareTo(y.$2.listing.id);
    });
    final items = [for (final s in scored.take(limit)) s.$2];
    return RecoPage(items: items, total: scored.length, listingId: listingId);
  }

  @override
  Future<RecoPage> recommendations({
    List<String> refs = const [],
    String? country,
    int limit = 20,
  }) async {
    final viewed = <Listing>[
      for (final id in refs.take(kRecentlyViewedCap))
        for (final l in mockListings)
          if (l.id == id) l,
    ];
    final viewedIds = {for (final v in viewed) v.id};
    final scored = <(double, RecoItem)>[];
    for (final c in mockListings) {
      if (viewedIds.contains(c.id)) continue;
      final trust = (c.supplier.trustScore ?? 0) / 100;
      Listing? match;
      for (final v in viewed) {
        if (v.category != null && v.category == c.category) {
          match = v;
          break;
        }
      }
      if (viewed.isNotEmpty && match == null) continue;
      final score = (match == null ? 0.0 : 1.0) + trust;
      final reason = match == null
          ? _reason('top_trusted')
          : _reason('because_viewed', ref: match.id);
      scored.add((score, RecoItem(listing: c, score: score / 2, reasons: [reason])));
    }
    scored.sort((x, y) {
      final byScore = y.$1.compareTo(x.$1);
      return byScore != 0 ? byScore : x.$2.listing.id.compareTo(y.$2.listing.id);
    });
    final perSupplier = <String, int>{};
    final items = <RecoItem>[];
    for (final s in scored) {
      final sid = s.$2.listing.supplier.id;
      if ((perSupplier[sid] ?? 0) >= 3) continue;
      perSupplier[sid] = (perSupplier[sid] ?? 0) + 1;
      items.add(s.$2);
      if (items.length >= limit) break;
    }
    return RecoPage(
      items: items,
      total: items.length,
      basedOn: [for (final v in viewed) v.id],
    );
  }
}

final recoRepositoryProvider = Provider<RecoRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockRecoRepository() : LiveRecoRepository(api);
});

class PriceHistoryArgs {
  const PriceHistoryArgs(this.listingId, this.days);
  final String listingId;
  final int days;

  @override
  bool operator ==(Object other) =>
      other is PriceHistoryArgs && other.listingId == listingId && other.days == days;

  @override
  int get hashCode => Object.hash(listingId, days);
}

final priceHistoryProvider =
    FutureProvider.autoDispose.family<PriceHistory, PriceHistoryArgs>(
  (ref, a) => ref.watch(recoRepositoryProvider).priceHistory(a.listingId, days: a.days),
);

final similarListingsProvider = FutureProvider.autoDispose.family<RecoPage, String>(
  (ref, id) => ref.watch(recoRepositoryProvider).similar(id),
);

/// Recommendations for the Discover tab, driven by the local recently viewed
/// ids. Waits (stays loading) until the stored ids have been read so the
/// first request already carries them.
final recommendationsProvider = FutureProvider.autoDispose<RecoPage>((ref) {
  final recent = ref.watch(recentlyViewedProvider);
  if (!recent.loaded) return Completer<RecoPage>().future;
  return ref.watch(recoRepositoryProvider).recommendations(refs: recent.ids);
});
