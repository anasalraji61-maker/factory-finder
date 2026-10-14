import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/watchlist/data/watch_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class WatchlistRepository {
  Future<List<WatchItem>> watchlist();

  /// [title] / [currentPrice] are display hints used by the mock only; the
  /// live backend resolves them from sourcing.
  Future<WatchItem> add(
    String listingId, {
    Money? targetPrice,
    String? dropThresholdPct,
    String? title,
    String? titleAr,
    Money? currentPrice,
  });

  /// Saves a search (`SearchQuery` body of POST /v1/watchlist). Idempotent.
  Future<WatchItem> addSearch(
    Map<String, dynamic> search, {
    String? title,
    String? titleAr,
  });

  Future<void> remove(String watchId);
  Future<AlertPage> alerts({bool unreadOnly = false});
  Future<PriceAlert> markRead(String alertId);
  Future<int> markAllRead();
  Future<int> unreadCount();
}

class LiveWatchlistRepository implements WatchlistRepository {
  LiveWatchlistRepository(this._api);
  final ApiClient _api;

  @override
  Future<List<WatchItem>> watchlist() async => parseWatchList(await _api.get('/v1/watchlist'));

  @override
  Future<WatchItem> add(
    String listingId, {
    Money? targetPrice,
    String? dropThresholdPct,
    String? title,
    String? titleAr,
    Money? currentPrice,
  }) async {
    final data = await _api.post('/v1/watchlist', body: {
      'listing_id': listingId,
      if (targetPrice != null) 'target_price': targetPrice.toJson(),
      if (dropThresholdPct != null && dropThresholdPct.isNotEmpty)
        'drop_threshold_pct': dropThresholdPct,
    });
    return WatchItem.fromJson(Map<String, dynamic>.from(data as Map));
  }

  @override
  Future<WatchItem> addSearch(
    Map<String, dynamic> search, {
    String? title,
    String? titleAr,
  }) async {
    final data = await _api.post('/v1/watchlist', body: {'search': search});
    return WatchItem.fromJson(Map<String, dynamic>.from(data as Map));
  }

  @override
  Future<void> remove(String watchId) async {
    await _api.delete('/v1/watchlist/$watchId');
  }

  @override
  Future<AlertPage> alerts({bool unreadOnly = false}) async {
    final data = await _api.get(
      '/v1/alerts',
      query: {if (unreadOnly) 'unread_only': 'true'},
    );
    return AlertPage.fromJson(Map<String, dynamic>.from(data as Map));
  }

  @override
  Future<PriceAlert> markRead(String alertId) async {
    final data = await _api.post('/v1/alerts/$alertId/read');
    return PriceAlert.fromJson(Map<String, dynamic>.from(data as Map));
  }

  @override
  Future<int> markAllRead() async {
    final data = await _api.post('/v1/alerts/read-all');
    if (data is Map && data['marked'] is num) return (data['marked'] as num).toInt();
    return 0;
  }

  @override
  Future<int> unreadCount() async {
    final data = await _api.get('/v1/alerts', query: {'unread_only': 'true', 'page_size': '1'});
    if (data is Map && data['unread_total'] is num) {
      return (data['unread_total'] as num).toInt();
    }
    return 0;
  }
}

class MockWatchlistRepository implements WatchlistRepository {
  MockWatchlistRepository({DateTime Function()? clock}) : _clock = clock ?? DateTime.now {
    final now = _clock();
    _watches.add(WatchItem(
      id: 'wat_001',
      listingId: 'lst_0041',
      title: 'LED panel light 40W',
      titleAr: 'لوحة إضاءة LED بقدرة 40 واط',
      targetPrice: const Money(amount: '2.50', currency: 'USD'),
      baselinePrice: const Money(amount: '3.00', currency: 'USD'),
      currentPrice: const Money(amount: '2.80', currency: 'USD'),
      available: true,
      createdAt: now.subtract(const Duration(days: 3)),
      lastCheckedAt: now.subtract(const Duration(hours: 2)),
    ));
    _alerts.add(PriceAlert(
      id: 'alt_001',
      watchId: 'wat_001',
      rule: 'price_drop',
      title: 'Price dropped',
      titleAr: 'انخفض السعر',
      body: 'LED panel light 40W fell from 3.00 to 2.80 USD.',
      bodyAr: 'انخفض سعر لوحة إضاءة LED من 3.00 إلى 2.80 دولار.',
      payload: const {
        'listing_ids': ['lst_0041'],
        'old_price': '3.00',
        'new_price': '2.80',
      },
      createdAt: now.subtract(const Duration(hours: 2)),
    ));
    _alerts.add(PriceAlert(
      id: 'alt_002',
      watchId: 'shp_a1b2c3d4e5f6',
      rule: kRuleShipmentStatus,
      title: 'Shipment update',
      titleAr: 'تحديث الشحنة',
      body: 'MSKU1234565: In transit -> Arrived at port.',
      bodyAr: 'MSKU1234565: في الطريق -> وصلت إلى الميناء.',
      payload: const {
        'shipment': {
          'shipment_id': 'shp_001',
          'kind': 'status_changed',
          'reference': 'MSKU1234565',
          'reference_type': 'container',
          'label': 'LED lights order',
          'status': 'arrived',
          'previous_status': 'in_transit',
          'delayed': false,
        },
      },
      createdAt: now.subtract(const Duration(hours: 5)),
    ));
    _alerts.add(PriceAlert(
      id: 'alt_003',
      watchId: 'shp_f6e5d4c3b2a1',
      rule: kRuleShipmentDelayed,
      title: 'Shipment delayed',
      titleAr: 'تأخّر الشحنة',
      body: 'TGHU7654320 is about 36 hours late.',
      bodyAr: 'الشحنة TGHU7654320 متأخرة نحو 36 ساعة.',
      payload: const {
        'shipment': {
          'shipment_id': 'shp_002',
          'kind': 'shipment_delayed',
          'reference': 'TGHU7654320',
          'reference_type': 'container',
          'status': 'in_transit',
          'eta': '2026-10-20T00:00:00Z',
          'delayed': true,
          'delay_hours': 36,
        },
      },
      createdAt: now.subtract(const Duration(hours: 8)),
    ));
  }

  final DateTime Function() _clock;
  final List<WatchItem> _watches = [];
  final List<PriceAlert> _alerts = [];
  int _seq = 1;

  @override
  Future<List<WatchItem>> watchlist() async => List<WatchItem>.of(_watches);

  @override
  Future<WatchItem> add(
    String listingId, {
    Money? targetPrice,
    String? dropThresholdPct,
    String? title,
    String? titleAr,
    Money? currentPrice,
  }) async {
    for (final w in _watches) {
      if (w.listingId == listingId) return w; // idempotent per target
    }
    final w = WatchItem(
      id: 'wat_${(++_seq).toString().padLeft(3, '0')}',
      listingId: listingId,
      title: title,
      titleAr: titleAr,
      targetPrice: targetPrice,
      dropThresholdPct: (dropThresholdPct == null || dropThresholdPct.isEmpty)
          ? '5'
          : dropThresholdPct,
      baselinePrice: currentPrice,
      currentPrice: currentPrice,
      available: true,
      createdAt: _clock(),
      lastCheckedAt: _clock(),
    );
    _watches.add(w);
    return w;
  }

  @override
  Future<WatchItem> addSearch(
    Map<String, dynamic> search, {
    String? title,
    String? titleAr,
  }) async {
    final key = search.toString();
    for (final w in _watches) {
      if (w.type == 'search' && w.search != null && w.search.toString() == key) {
        return w; // idempotent per target
      }
    }
    final w = WatchItem(
      id: 'wat_${(++_seq).toString().padLeft(3, '0')}',
      type: 'search',
      search: Map<String, dynamic>.from(search),
      title: title,
      titleAr: titleAr,
      resultCount: 0,
      createdAt: _clock(),
      lastCheckedAt: _clock(),
    );
    _watches.add(w);
    return w;
  }

  @override
  Future<void> remove(String watchId) async {
    final before = _watches.length;
    _watches.removeWhere((w) => w.id == watchId);
    if (_watches.length == before) {
      throw ApiException(status: 404, code: 'not_found', message: 'watch not found');
    }
  }

  @override
  Future<AlertPage> alerts({bool unreadOnly = false}) async {
    final list = [
      for (final a in _alerts)
        if (!unreadOnly || !a.read) a,
    ]..sort((a, b) => (b.createdAt ?? DateTime(1970)).compareTo(a.createdAt ?? DateTime(1970)));
    return AlertPage(
      items: list,
      total: list.length,
      page: 1,
      pageSize: list.length,
      unreadTotal: _alerts.where((a) => !a.read).length,
    );
  }

  @override
  Future<PriceAlert> markRead(String alertId) async {
    final i = _alerts.indexWhere((a) => a.id == alertId);
    if (i < 0) {
      throw ApiException(status: 404, code: 'not_found', message: 'alert not found');
    }
    if (!_alerts[i].read) {
      _alerts[i] = _alerts[i].copyWith(read: true, readAt: _clock());
    }
    return _alerts[i];
  }

  @override
  Future<int> markAllRead() async {
    var n = 0;
    for (var i = 0; i < _alerts.length; i++) {
      if (!_alerts[i].read) {
        _alerts[i] = _alerts[i].copyWith(read: true, readAt: _clock());
        n++;
      }
    }
    return n;
  }

  @override
  Future<int> unreadCount() async => _alerts.where((a) => !a.read).length;
}

final watchlistRepositoryProvider = Provider<WatchlistRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockWatchlistRepository() : LiveWatchlistRepository(api);
});

final watchlistProvider = FutureProvider.autoDispose<List<WatchItem>>(
  (ref) => ref.watch(watchlistRepositoryProvider).watchlist(),
);

final alertsProvider = FutureProvider.autoDispose<AlertPage>(
  (ref) => ref.watch(watchlistRepositoryProvider).alerts(),
);

/// Unread alert count for the bell badge. Guests / errors show no badge.
final unreadAlertsProvider = FutureProvider.autoDispose<int>((ref) async {
  try {
    return await ref.watch(watchlistRepositoryProvider).unreadCount();
  } catch (_) {
    return 0;
  }
});
