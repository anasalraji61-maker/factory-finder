import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/data/mock_catalog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

String _ar(String key) => AppStrings.lookup('ar', key);

ApiException get _offline =>
    ApiException(code: 'network_error', message: 'socket closed');

/// Fails the first call of each endpoint, then answers from the mock catalog.
class _FlakyRepo extends DiscoverRepository {
  _FlakyRepo() : super(ApiClient(baseUrl: 'http://fake', isMock: true));

  bool failSearch = true;
  bool failListing = true;
  bool failSupplier = true;

  @override
  Future<PageResult<Listing>> search(ListingQuery q) async {
    if (failSearch) throw _offline;
    return filterMockListings(q);
  }

  @override
  Future<Listing> getListing(String id) async {
    if (failListing) throw _offline;
    return mockListings.first;
  }

  @override
  Future<SupplierSummary> getSupplier(String id) async {
    if (failSupplier) throw _offline;
    return mockSuppliers.values.first;
  }

  @override
  Future<List<Listing>> trending() async => const <Listing>[];
}

void main() {
  setUpWidgetTests();

  testWidgets('search: offline error shows localized message, retry recovers',
      (tester) async {
    final repo = _FlakyRepo();
    await pumpApp(
      tester,
      location: '/discover/search?q=solar',
      logicalSize: const Size(540, 2400),
      overrides: [discoverRepositoryProvider.overrideWithValue(repo)],
    );
    expect(find.text(_ar('offline.message')), findsWidgets);
    repo.failSearch = false;
    await tester.tap(find.text(_ar('common.retry')).first);
    await settle(tester);
    expect(find.text(_ar('offline.message')), findsNothing);
    await disposeApp(tester);
  });

  testWidgets('listing detail: offline error then retry succeeds',
      (tester) async {
    final repo = _FlakyRepo();
    await pumpApp(
      tester,
      location: '/listing/${mockListings.first.id}',
      logicalSize: const Size(540, 2400),
      overrides: [discoverRepositoryProvider.overrideWithValue(repo)],
    );
    expect(find.byType(ErrorState), findsOneWidget);
    expect(find.text(_ar('offline.message')), findsOneWidget);
    repo.failListing = false;
    await tester.tap(find.text(_ar('common.retry')));
    await settle(tester);
    expect(find.byType(ErrorState), findsNothing);
    await disposeApp(tester);
  });

  testWidgets('supplier: offline error then retry succeeds', (tester) async {
    final repo = _FlakyRepo()..failSearch = false;
    await pumpApp(
      tester,
      location: '/supplier/${mockSuppliers.keys.first}',
      logicalSize: const Size(540, 2400),
      overrides: [discoverRepositoryProvider.overrideWithValue(repo)],
    );
    expect(find.byType(ErrorState), findsOneWidget);
    expect(find.text(_ar('offline.message')), findsOneWidget);
    repo.failSupplier = false;
    await tester.tap(find.text(_ar('common.retry')));
    await settle(tester);
    expect(find.text(_ar('offline.message')), findsNothing);
    await disposeApp(tester);
  });
}
