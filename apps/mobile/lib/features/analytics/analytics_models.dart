/// Supplier analytics (GET /v1/my/analytics). Parsing is tolerant: missing
/// numbers become 0, malformed rows are skipped.

int _int(Object? v) {
  if (v is num) return v.isFinite ? v.toInt() : 0;
  if (v is String) return int.tryParse(v) ?? 0;
  return 0;
}

double? _doubleOrNull(Object? v) {
  if (v is num) return v.isFinite ? v.toDouble() : null;
  if (v is String) return double.tryParse(v);
  return null;
}

String _str(Object? v) => v is String ? v : (v?.toString() ?? '');

Map<String, dynamic>? _map(Object? v) =>
    v is Map ? Map<String, dynamic>.from(v) : null;

/// Counters the API reports per period / day / listing.
enum AnalyticsMetric {
  impression('impression'),
  view('view'),
  contactClick('contact_click'),
  share('share'),
  watchlistAdd('watchlist_add'),
  report('report');

  const AnalyticsMetric(this.json);
  final String json;

  /// A rise is bad news for these metrics (arrow colours are inverted).
  bool get risingIsBad => this == report;
}

class AnalyticsCounts {
  const AnalyticsCounts({
    this.impression = 0,
    this.view = 0,
    this.contactClick = 0,
    this.share = 0,
    this.watchlistAdd = 0,
    this.report = 0,
  });

  factory AnalyticsCounts.fromJson(Object? json) {
    final m = _map(json) ?? const <String, dynamic>{};
    return AnalyticsCounts(
      impression: _int(m['impression']),
      view: _int(m['view']),
      contactClick: _int(m['contact_click']),
      share: _int(m['share']),
      watchlistAdd: _int(m['watchlist_add']),
      report: _int(m['report']),
    );
  }

  static const AnalyticsCounts zero = AnalyticsCounts();

  final int impression;
  final int view;
  final int contactClick;
  final int share;
  final int watchlistAdd;
  final int report;

  int of(AnalyticsMetric m) {
    switch (m) {
      case AnalyticsMetric.impression:
        return impression;
      case AnalyticsMetric.view:
        return view;
      case AnalyticsMetric.contactClick:
        return contactClick;
      case AnalyticsMetric.share:
        return share;
      case AnalyticsMetric.watchlistAdd:
        return watchlistAdd;
      case AnalyticsMetric.report:
        return report;
    }
  }

  bool get isZero =>
      impression == 0 &&
      view == 0 &&
      contactClick == 0 &&
      share == 0 &&
      watchlistAdd == 0 &&
      report == 0;

  AnalyticsCounts operator +(AnalyticsCounts o) => AnalyticsCounts(
        impression: impression + o.impression,
        view: view + o.view,
        contactClick: contactClick + o.contactClick,
        share: share + o.share,
        watchlistAdd: watchlistAdd + o.watchlistAdd,
        report: report + o.report,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'impression': impression,
        'view': view,
        'contact_click': contactClick,
        'share': share,
        'watchlist_add': watchlistAdd,
        'report': report,
      };
}

class AnalyticsPeriod {
  const AnalyticsPeriod({
    required this.days,
    this.from = '',
    this.to = '',
    this.previousFrom = '',
    this.previousTo = '',
  });

  factory AnalyticsPeriod.fromJson(Object? json, {int fallbackDays = 30}) {
    final m = _map(json) ?? const <String, dynamic>{};
    final d = _int(m['days']);
    return AnalyticsPeriod(
      days: d > 0 ? d : fallbackDays,
      from: _str(m['from']),
      to: _str(m['to']),
      previousFrom: _str(m['previous_from']),
      previousTo: _str(m['previous_to']),
    );
  }

  final int days;
  final String from;
  final String to;
  final String previousFrom;
  final String previousTo;
}

class AnalyticsDay {
  const AnalyticsDay({required this.date, required this.counts});

  final String date;
  final AnalyticsCounts counts;
}

class AnalyticsListingRow {
  const AnalyticsListingRow({
    required this.listingId,
    required this.title,
    required this.status,
    required this.counts,
    this.viewToContact,
  });

  factory AnalyticsListingRow.fromJson(Map<String, dynamic> m) =>
      AnalyticsListingRow(
        listingId: _str(m['listing_id']),
        title: _str(m['title']),
        status: _str(m['status']),
        counts: AnalyticsCounts.fromJson(m),
        viewToContact: _doubleOrNull(m['view_to_contact']),
      );

  final String listingId;
  final String title;
  final String status;
  final AnalyticsCounts counts;

  /// 0..1, null when there were no views.
  final double? viewToContact;
}

class AnalyticsConversion {
  const AnalyticsConversion({
    this.viewToContact,
    this.impressionToView,
    this.previousViewToContact,
  });

  factory AnalyticsConversion.fromJson(Object? json) {
    final m = _map(json) ?? const <String, dynamic>{};
    return AnalyticsConversion(
      viewToContact: _doubleOrNull(m['view_to_contact']),
      impressionToView: _doubleOrNull(m['impression_to_view']),
      previousViewToContact: _doubleOrNull(m['previous_view_to_contact']),
    );
  }

  final double? viewToContact;
  final double? impressionToView;
  final double? previousViewToContact;
}

class SupplierAnalytics {
  const SupplierAnalytics({
    required this.period,
    required this.totals,
    required this.previousTotals,
    this.changePct = const <String, double?>{},
    this.conversion = const AnalyticsConversion(),
    this.uniqueViewers = 0,
    this.uniqueContacts = 0,
    this.uniqueNote = '',
    this.series = const <AnalyticsDay>[],
    this.listings = const <AnalyticsListingRow>[],
    this.listingsTotal = 0,
  });

  factory SupplierAnalytics.fromJson(Object? json, {int fallbackDays = 30}) {
    final m = _map(json);
    if (m == null) {
      throw const FormatException('analytics: expected an object');
    }
    final change = <String, double?>{};
    final rawChange = _map(m['change_pct']);
    if (rawChange != null) {
      rawChange.forEach((k, v) => change[k] = _doubleOrNull(v));
    }
    final unique = _map(m['unique_viewers']) ?? const <String, dynamic>{};
    final series = <AnalyticsDay>[
      if (m['series'] is List)
        for (final e in m['series'] as List)
          if (e is Map)
            AnalyticsDay(
              date: _str(e['date']),
              counts: AnalyticsCounts.fromJson(e),
            ),
    ];
    final rows = <AnalyticsListingRow>[
      if (m['listings'] is List)
        for (final e in m['listings'] as List)
          if (e is Map)
            AnalyticsListingRow.fromJson(Map<String, dynamic>.from(e)),
    ];
    return SupplierAnalytics(
      period: AnalyticsPeriod.fromJson(m['period'], fallbackDays: fallbackDays),
      totals: AnalyticsCounts.fromJson(m['totals']),
      previousTotals: AnalyticsCounts.fromJson(m['previous_totals']),
      changePct: change,
      conversion: AnalyticsConversion.fromJson(m['conversion']),
      uniqueViewers: _int(unique['view']),
      uniqueContacts: _int(unique['contact_click']),
      uniqueNote: _str(unique['note']),
      series: series,
      listings: rows,
      listingsTotal: m['listings_total'] == null
          ? rows.length
          : _int(m['listings_total']),
    );
  }

  final AnalyticsPeriod period;
  final AnalyticsCounts totals;
  final AnalyticsCounts previousTotals;

  /// Percent per metric json key; null value = previous period was 0.
  final Map<String, double?> changePct;
  final AnalyticsConversion conversion;
  final int uniqueViewers;
  final int uniqueContacts;
  final String uniqueNote;
  final List<AnalyticsDay> series;
  final List<AnalyticsListingRow> listings;
  final int listingsTotal;

  /// No activity at all in the period (and nothing in the series).
  bool get isEmpty => totals.isZero && series.every((d) => d.counts.isZero);

  double? changeOf(AnalyticsMetric m) => changePct[m.json];
}
