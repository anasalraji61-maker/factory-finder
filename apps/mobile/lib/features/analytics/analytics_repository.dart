import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/analytics/analytics_logic.dart';
import 'package:factory_finder/features/analytics/analytics_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Listings that exist in mock mode: id, title, share of the traffic.
const List<(String, String, double)> kMockAnalyticsListings =
    <(String, String, double)>[
  ('lst_mock_a1', 'LED panel light 60x60', 0.5),
  ('lst_mock_a2', 'Solar inverter 5 kW', 0.3),
  ('lst_mock_a3', 'Hydraulic press line', 0.2),
];

String _dateOf(DateTime d) {
  String two(int v) => v.toString().padLeft(2, '0');
  return '${d.year}-${two(d.month)}-${two(d.day)}';
}

/// Deterministic analytics for mock mode and tests. Throws the same
/// [ApiException]s as the server (422 bad `days`, 404 unknown listing).
SupplierAnalytics buildMockAnalytics({
  int days = kDefaultAnalyticsDays,
  String? listingId,
  DateTime? now,
}) {
  if (!kAnalyticsPeriods.contains(days)) {
    throw ApiException(
        status: 422, code: 'validation_error', message: 'days must be 7, 30 or 90');
  }
  var weight = 1.0;
  if (listingId != null) {
    final hit = kMockAnalyticsListings.where((l) => l.$1 == listingId);
    if (hit.isEmpty) {
      throw ApiException(
          status: 404, code: 'not_found', message: 'Listing not found');
    }
    weight = hit.first.$3;
  }
  final today = (now ?? DateTime.now()).toUtc();
  final end = DateTime.utc(today.year, today.month, today.day);

  AnalyticsCounts day(int index, {required int salt}) {
    int v(int base, int spread, int k) =>
        (((base + ((index + salt) * k) % spread) * weight)).round();
    final view = v(20, 13, 7);
    return AnalyticsCounts(
      impression: v(160, 41, 11),
      view: view,
      contactClick: (view * weight * 0.12).round() % 7 + (index % 3 == 0 ? 1 : 0),
      share: index % 4 == 0 ? 1 : 0,
      watchlistAdd: index % 5 == 0 ? 1 : 0,
      report: 0,
    );
  }

  final series = <AnalyticsDay>[];
  var totals = AnalyticsCounts.zero;
  var previous = AnalyticsCounts.zero;
  for (var i = 0; i < days; i++) {
    final c = day(i, salt: 3);
    totals = totals + c;
    series.add(AnalyticsDay(
      date: _dateOf(end.subtract(Duration(days: days - 1 - i))),
      counts: c,
    ));
    previous = previous + day(i, salt: 11);
  }

  double? pct(int cur, int prev) =>
      prev == 0 ? null : (cur - prev) / prev * 100;
  double? ratio(int a, int b) =>
      b == 0 ? null : (a / b).clamp(0.0, 1.0).toDouble();

  final rows = <AnalyticsListingRow>[
    for (final l in kMockAnalyticsListings)
      if (listingId == null || l.$1 == listingId)
        AnalyticsListingRow(
          listingId: l.$1,
          title: l.$2,
          status: 'published',
          counts: AnalyticsCounts(
            impression: (totals.impression * l.$3 / weight).round(),
            view: (totals.view * l.$3 / weight).round(),
            contactClick: (totals.contactClick * l.$3 / weight).round(),
            share: (totals.share * l.$3 / weight).round(),
            watchlistAdd: (totals.watchlistAdd * l.$3 / weight).round(),
          ),
          viewToContact: ratio(
            (totals.contactClick * l.$3 / weight).round(),
            (totals.view * l.$3 / weight).round(),
          ),
        ),
  ];

  return SupplierAnalytics(
    period: AnalyticsPeriod(
      days: days,
      from: series.first.date,
      to: series.last.date,
      previousFrom: _dateOf(end.subtract(Duration(days: 2 * days - 1))),
      previousTo: _dateOf(end.subtract(Duration(days: days))),
    ),
    totals: totals,
    previousTotals: previous,
    changePct: <String, double?>{
      for (final m in AnalyticsMetric.values)
        m.json: pct(totals.of(m), previous.of(m)),
    },
    conversion: AnalyticsConversion(
      viewToContact: ratio(totals.contactClick, totals.view),
      impressionToView: ratio(totals.view, totals.impression),
      previousViewToContact: ratio(previous.contactClick, previous.view),
    ),
    uniqueViewers: (totals.view * 0.7).round(),
    uniqueContacts: (totals.contactClick * 0.9).round(),
    uniqueNote: 'Estimate: a person on two days counts twice.',
    series: series,
    listings: rows,
    listingsTotal: rows.length,
  );
}

class AnalyticsRepository {
  AnalyticsRepository(this._api, {DateTime Function()? clock})
      : _clock = clock ?? DateTime.now;

  final ApiClient _api;
  final DateTime Function() _clock;

  /// GET /v1/my/analytics. Throws [ApiException] (403 not a supplier, 404 not
  /// your listing, 422 bad days).
  Future<SupplierAnalytics> fetch({
    int days = kDefaultAnalyticsDays,
    String? listingId,
  }) async {
    if (_api.isMock) {
      await mockDelay(200);
      return buildMockAnalytics(days: days, listingId: listingId, now: _clock());
    }
    final json = await _api.get('/v1/my/analytics', query: <String, dynamic>{
      'days': days,
      if (listingId != null && listingId.isNotEmpty) 'listing_id': listingId,
    });
    try {
      return SupplierAnalytics.fromJson(json, fallbackDays: days);
    } on FormatException {
      throw ApiException(
          status: null, code: 'bad_response', message: 'Unexpected response');
    }
  }
}

final analyticsRepositoryProvider = Provider<AnalyticsRepository>(
  (ref) => AnalyticsRepository(ref.watch(apiClientProvider)),
);
