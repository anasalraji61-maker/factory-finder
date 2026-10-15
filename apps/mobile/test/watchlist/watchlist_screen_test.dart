import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/watchlist/data/watch_repository.dart';
import 'package:factory_finder/features/watchlist/screens/watchlist_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

/// Mock repository whose remove() can be made to fail.
class _RemoveRepo extends MockWatchlistRepository {
  bool failRemove = true;

  @override
  Future<void> remove(String watchId) async {
    if (failRemove) {
      throw ApiException(status: 500, code: 'server_error', message: 'boom');
    }
    return super.remove(watchId);
  }
}

String _ar(String key) => AppStrings.lookup('ar', key);

void main() {
  setUpWidgetTests();

  testWidgets('watchlist: failed remove keeps the card, retry removes it', (tester) async {
    final repo = _RemoveRepo();
    await pumpApp(
      tester,
      location: '/watchlist',
      logicalSize: const Size(540, 2400),
      overrides: [watchlistRepositoryProvider.overrideWithValue(repo)],
    );
    final removeBtn = find.byTooltip(_ar('watch.remove'));
    expect(removeBtn, findsOneWidget);
    expect(find.text(_ar('watch.empty_title')), findsNothing);

    await tester.tap(removeBtn);
    await settle(tester, frames: 4);
    expect(find.text(_ar('watch.failed')), findsOneWidget);
    expect(removeBtn, findsOneWidget);
    expect((await repo.watchlist()).length, 1);

    // Let the failure snackbar expire so the next one can show.
    await tester.pump(const Duration(seconds: 5));
    await settle(tester, frames: 4);

    repo.failRemove = false;
    await tester.tap(removeBtn);
    await settle(tester, frames: 6);
    expect(find.text(_ar('watch.removed')), findsOneWidget);
    expect(removeBtn, findsNothing);
    expect(find.text(_ar('watch.empty_title')), findsOneWidget);
    expect(await repo.watchlist(), isEmpty);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('watch sheet: validates both fields, then returns the draft', (tester) async {
    await pumpApp(tester, logicalSize: const Size(540, 2400));
    final host = tester.element(find.byType(NavigationBar));

    WatchDraft? result;
    var done = false;
    showWatchSheet(host, currency: 'USD').then((d) {
      result = d;
      done = true;
    });
    await settle(tester, frames: 6);

    final fields = find.descendant(
      of: find.byType(BottomSheet),
      matching: find.byType(TextField),
    );
    expect(fields, findsNWidgets(2));
    final confirm = find.text(_ar('watch.confirm'));
    expect(confirm, findsOneWidget);

    // Bad target price blocks submit and shows the error.
    await tester.enterText(fields.at(0), '0');
    await tester.tap(confirm);
    await settle(tester, frames: 3);
    expect(find.text(_ar('watch.err.target')), findsOneWidget);
    expect(find.text(_ar('watch.err.pct')), findsNothing);
    expect(done, isFalse);

    // Target fixed, drop percentage out of range.
    await tester.enterText(fields.at(0), '2.5');
    await tester.enterText(fields.at(1), '101');
    await tester.tap(confirm);
    await settle(tester, frames: 3);
    expect(find.text(_ar('watch.err.target')), findsNothing);
    expect(find.text(_ar('watch.err.pct')), findsOneWidget);
    expect(done, isFalse);

    // Valid input closes the sheet with the typed values.
    await tester.enterText(fields.at(1), '10');
    await tester.tap(confirm);
    await settle(tester, frames: 6);
    expect(done, isTrue);
    expect(result!.targetPrice!.amount, '2.5');
    expect(result!.targetPrice!.currency, 'USD');
    expect(result!.dropPct, '10');
    expect(find.byType(BottomSheet), findsNothing);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
