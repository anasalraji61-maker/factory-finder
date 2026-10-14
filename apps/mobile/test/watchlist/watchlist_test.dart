import 'dart:convert';
import 'dart:io';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/watchlist/data/watch_models.dart';
import 'package:factory_finder/features/watchlist/data/watch_repository.dart';
import 'package:factory_finder/features/watchlist/screens/watchlist_screen.dart';
import 'package:factory_finder/features/watchlist/watchlist_strings.dart';
import 'package:flutter_test/flutter_test.dart';

dynamic _load(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

void main() {
  group('models (live fixtures)', () {
    test('watchlist', () {
      final list = parseWatchList(_load('watchlist'));
      expect(list, hasLength(2));
      final w = list.first;
      expect(w.id, 'wat_1a2b3c4d');
      expect(w.isListing, isTrue);
      expect(w.listingId, 'lst_0041');
      expect(w.targetPrice?.amount, '2.50');
      expect(w.currentPrice?.amount, '2.40');
      expect(w.reachedTarget, isTrue);
      expect(w.dropThresholdPct, '5');
      expect(w.displayTitle('ar'), contains('LED'));
      expect(w.displayTitle('en'), 'LED panel light 40W');
      expect(w.lastCheckedAt, isNotNull);
      final s = list[1];
      expect(s.type, 'search');
      expect(s.isListing, isFalse);
      expect(s.currentPrice, isNull);
      expect(s.resultCount, 12);
      expect(s.reachedTarget, isFalse);
    });

    test('alerts page', () {
      final page = AlertPage.fromJson(Map<String, dynamic>.from(_load('alerts') as Map));
      expect(page.total, 2);
      expect(page.unreadTotal, 1);
      expect(page.items.first.read, isFalse);
      expect(page.items.first.listingId, 'lst_0041');
      expect(page.items.first.displayTitle('ar'), 'تم بلوغ السعر المستهدف');
      expect(page.items.first.displayTitle('en'), 'Target price reached');
      expect(page.items[1].read, isTrue);
      expect(page.items[1].listingId, isNull);
      expect(page.items[1].readAt, isNotNull);
    });

    test('tolerant of missing and odd fields', () {
      final w = WatchItem.fromJson({'id': 'x'});
      expect(w.type, 'listing');
      expect(w.active, isTrue);
      expect(w.targetPrice, isNull);
      final a = PriceAlert.fromJson({'id': 'a', 'payload': 'oops'});
      expect(a.payload, isEmpty);
      expect(a.read, isFalse);
      final p = AlertPage.fromJson({'items': 'nope'});
      expect(p.items, isEmpty);
      expect(parseWatchList(null), isEmpty);
    });
  });

  group('mock repository', () {
    test('seeded state and unread count', () async {
      final repo = MockWatchlistRepository();
      expect(await repo.watchlist(), hasLength(1));
      expect(await repo.unreadCount(), 1);
      final page = await repo.alerts(unreadOnly: true);
      expect(page.items, hasLength(1));
    });

    test('add is idempotent per listing, remove works', () async {
      final repo = MockWatchlistRepository();
      final a = await repo.add('lst_9',
          targetPrice: const Money(amount: '1.00', currency: 'USD'),
          title: 'T',
          currentPrice: const Money(amount: '2.00', currency: 'USD'));
      final b = await repo.add('lst_9');
      expect(b.id, a.id);
      expect(a.dropThresholdPct, '5');
      expect((await repo.watchlist()), hasLength(2));
      await repo.remove(a.id);
      expect((await repo.watchlist()), hasLength(1));
      expect(() => repo.remove('nope'), throwsA(isA<ApiException>()));
    });

    test('mark read and mark all read', () async {
      final repo = MockWatchlistRepository();
      final r = await repo.markRead('alt_001');
      expect(r.read, isTrue);
      expect(await repo.unreadCount(), 0);
      expect(await repo.markAllRead(), 0);
      expect(() => repo.markRead('zzz'), throwsA(isA<ApiException>()));
    });
  });

  group('sheet validation and strings', () {
    test('target price', () {
      expect(validateTargetPrice(''), isNull);
      expect(validateTargetPrice('2.5'), isNull);
      expect(validateTargetPrice('0'), 'watch.err.target');
      expect(validateTargetPrice('abc'), 'watch.err.target');
    });
    test('drop pct', () {
      expect(validateDropPct(''), isNull);
      expect(validateDropPct('10'), isNull);
      expect(validateDropPct('101'), 'watch.err.pct');
      expect(validateDropPct('-1'), 'watch.err.pct');
    });
    test('ar and en have identical keys', () {
      expect(watchlistStrings['ar']!.keys.toSet(), watchlistStrings['en']!.keys.toSet());
    });
  });
}
