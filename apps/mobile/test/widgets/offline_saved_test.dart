import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/data/mock_catalog.dart';
import 'package:factory_finder/features/discover/data/search_facets.dart';
import 'package:factory_finder/features/feed/feed_models.dart';
import 'package:factory_finder/features/feed/feed_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

/// Pretends the network is down and the saved copy is served.
class _SavedDiscover extends DiscoverRepository {
  _SavedDiscover(this.fromCache)
      : super(ApiClient(baseUrl: 'http://x', isMock: true));

  final bool fromCache;

  @override
  Future<PageResult<Listing>> search(ListingQuery q) async {
    final items = mockListings.take(3).toList();
    return ListingPage(
      items: items,
      total: items.length,
      page: 1,
      pageSize: 50,
      fromCache: fromCache,
    );
  }
}

class _SavedFeed extends MockFeedRepository {
  _SavedFeed(this.fromCache);

  final bool fromCache;

  @override
  Future<FeedPage<FeedPost>> home({String? cursor, int limit = kFeedPageSize}) async {
    final page = await trending(cursor: cursor, limit: limit);
    return FeedPage<FeedPost>(
      items: page.items,
      nextCursor: page.nextCursor,
      source: FeedSource.following,
      fromCache: fromCache,
    );
  }
}

void main() {
  setUpWidgetTests();

  const savedNote = 'نعرض النتائج المحفوظة من آخر مرة';

  testWidgets('search shows the saved-results note when served from cache', (tester) async {
    await pumpApp(
      tester,
      location: '/discover/search',
      overrides: [discoverRepositoryProvider.overrideWithValue(_SavedDiscover(true))],
    );
    expect(find.byKey(const ValueKey('offline-banner')), findsOneWidget);
    expect(find.text(savedNote), findsOneWidget);
    expect(find.text('أنت غير متصل بالإنترنت'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('search shows no banner for live results', (tester) async {
    await pumpApp(
      tester,
      location: '/discover/search',
      overrides: [discoverRepositoryProvider.overrideWithValue(_SavedDiscover(false))],
    );
    expect(find.byKey(const ValueKey('offline-banner')), findsNothing);
    expect(find.text(savedNote), findsNothing);
    await disposeApp(tester);
  });

  testWidgets('discover home shows the saved-results note when served from cache',
      (tester) async {
    await pumpApp(
      tester,
      location: '/discover',
      overrides: [discoverRepositoryProvider.overrideWithValue(_SavedDiscover(true))],
    );
    expect(find.text(savedNote), findsOneWidget);
    await disposeApp(tester);
  });

  testWidgets('home feed shows the saved-results note when served from cache',
      (tester) async {
    await pumpApp(
      tester,
      location: '/feed',
      overrides: [feedRepositoryProvider.overrideWithValue(_SavedFeed(true))],
    );
    await tester.tap(find.byKey(const ValueKey<String>('feed-mode-home')));
    await settle(tester);
    expect(find.text(savedNote), findsOneWidget);
    await disposeApp(tester);
  });

  testWidgets('home feed shows no banner for live pages', (tester) async {
    await pumpApp(
      tester,
      location: '/feed',
      overrides: [feedRepositoryProvider.overrideWithValue(_SavedFeed(false))],
    );
    await tester.tap(find.byKey(const ValueKey<String>('feed-mode-home')));
    await settle(tester);
    expect(find.byKey(const ValueKey('offline-banner')), findsNothing);
    await disposeApp(tester);
  });
}
