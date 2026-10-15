import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/analytics/listing_events.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

ListingEventReporter _mockReporter() =>
    ListingEventReporter(ApiClient(baseUrl: 'http://unused.invalid', isMock: true));

void main() {
  setUpWidgetTests();

  testWidgets('listing detail records view, share and contact_click once each',
      (tester) async {
    final reporter = _mockReporter();
    await pumpApp(
      tester,
      location: '/listing/lst_001',
      overrides: [listingEventReporterProvider.overrideWithValue(reporter)],
    );
    await settle(tester, frames: 6);

    expect(reporter.mockEvents,
        const <ListingEventRecord>[ListingEventRecord('lst_001', ListingEventType.view)]);

    await tester.tap(find.byKey(const ValueKey<String>('listing-share')));
    await settle(tester, frames: 3);
    await tester.tap(find.byKey(const ValueKey<String>('listing-share'))); // duplicate
    await settle(tester, frames: 3);
    expect(reporter.mockEvents.where((e) => e.type == ListingEventType.share),
        hasLength(1));

    await tester.tap(find.text('راسل المورد').first);
    await settle(tester, frames: 6);
    expect(
      reporter.mockEvents.map((e) => e.type).toList(),
      <ListingEventType>[
        ListingEventType.view,
        ListingEventType.share,
        ListingEventType.contactClick,
      ],
    );
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('My products links to the analytics screen (mock data)', (tester) async {
    await pumpApp(tester, location: '/my-products');
    await settle(tester, frames: 6);

    await tester.tap(find.byKey(const ValueKey<String>('myp-analytics')));
    await settle(tester, frames: 10);

    expect(find.text('إحصائيات المنتجات'), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('ana-kpi-view')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('ana-chart')), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
