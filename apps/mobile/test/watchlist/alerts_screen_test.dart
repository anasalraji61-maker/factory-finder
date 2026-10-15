import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/watchlist/data/watch_models.dart';
import 'package:factory_finder/features/watchlist/data/watch_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

/// Mock repository whose alert list can be switched to fail.
class _FlakyAlertsRepo extends MockWatchlistRepository {
  bool fail = true;

  @override
  Future<AlertPage> alerts({bool unreadOnly = false}) async {
    if (fail) {
      throw ApiException(status: 500, code: 'server_error', message: 'boom');
    }
    return super.alerts(unreadOnly: unreadOnly);
  }
}

String _ar(String key) => AppStrings.lookup('ar', key);

void main() {
  setUpWidgetTests();

  testWidgets('alerts: one icon per rule, tap marks read, mark all clears', (tester) async {
    final repo = MockWatchlistRepository();
    final router = await pumpApp(
      tester,
      location: '/alerts',
      logicalSize: const Size(540, 2400),
      overrides: [watchlistRepositoryProvider.overrideWithValue(repo)],
    );

    expect(find.byKey(const Key('alert_icon_price_drop')), findsOneWidget);
    expect(find.byKey(const Key('alert_icon_$kRuleShipmentStatus')), findsOneWidget);
    expect(find.byKey(const Key('alert_icon_$kRuleShipmentDelayed')), findsOneWidget);
    expect(find.text(_ar('alerts.mark_all')), findsOneWidget);
    expect(await repo.unreadCount(), 3);

    // Opening an unread alert marks it read, then navigates away.
    await tester.tap(find.byKey(const Key('alert_icon_price_drop')));
    await settle(tester, frames: 6);
    expect(await repo.unreadCount(), 2);
    router.pop();
    await settle(tester, frames: 6);

    // The "mark all" action disappears once nothing is unread.
    expect(find.text(_ar('alerts.mark_all')), findsOneWidget);
    await tester.tap(find.text(_ar('alerts.mark_all')));
    await settle(tester, frames: 6);
    expect(await repo.unreadCount(), 0);
    expect(find.text(_ar('alerts.mark_all')), findsNothing);
    expect(find.byKey(const Key('alert_icon_price_drop')), findsOneWidget);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('alerts: error state offers retry and recovers', (tester) async {
    final repo = _FlakyAlertsRepo();
    await pumpApp(
      tester,
      location: '/alerts',
      logicalSize: const Size(540, 2400),
      overrides: [watchlistRepositoryProvider.overrideWithValue(repo)],
    );
    expect(find.text(_ar('common.retry')), findsOneWidget);
    expect(find.byKey(const Key('alert_icon_price_drop')), findsNothing);

    repo.fail = false;
    await tester.tap(find.text(_ar('common.retry')));
    await settle(tester, frames: 6);
    expect(find.text(_ar('common.retry')), findsNothing);
    expect(find.byKey(const Key('alert_icon_price_drop')), findsOneWidget);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
