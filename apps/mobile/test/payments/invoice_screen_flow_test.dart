import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/payments/payments_models.dart';
import 'package:factory_finder/features/payments/payments_repository.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

final Deal _deal = Deal(
  id: 'deal_1',
  requestId: 'req_1',
  offerId: 'off_1',
  subtotal: const Money(amount: '1000.00', currency: 'USD'),
  commission: const Money(amount: '30.00', currency: 'USD'),
  createdAt: DateTime.utc(2026, 10, 14),
);

String _ar(String key) => AppStrings.lookup('ar', key);

void main() {
  setUpWidgetTests();

  testWidgets('invoice: keep keeps it open, confirm cancels and hides pay details',
      (tester) async {
    final repo = MockPaymentsRepository(delayMs: 0);
    final inv = repo.createSync(_deal, InvoiceKind.commission);
    await pumpApp(
      tester,
      location: '/invoice/${inv.id}',
      logicalSize: const Size(540, 2400),
      overrides: [paymentsRepositoryProvider.overrideWithValue(repo)],
    );
    expect(find.byKey(const Key('invoice_cancel_button')), findsOneWidget);
    expect(find.byKey(const Key('invoice_copy_address')), findsOneWidget);

    // Dialog dismissed with "keep": nothing changes.
    await tester.tap(find.byKey(const Key('invoice_cancel_button')));
    await settle(tester, frames: 4);
    expect(find.byKey(const Key('invoice_cancel_confirm')), findsOneWidget);
    await tester.tap(find.text(_ar('pay.cancel.keep')));
    await settle(tester, frames: 4);
    expect(find.byKey(const Key('invoice_cancel_confirm')), findsNothing);
    expect(find.byKey(const Key('invoice_cancel_button')), findsOneWidget);

    // Confirmed: invoice becomes failed/cancelled and loses its pay details.
    await tester.tap(find.byKey(const Key('invoice_cancel_button')));
    await settle(tester, frames: 4);
    await tester.tap(find.byKey(const Key('invoice_cancel_confirm')));
    await settle(tester, frames: 6);
    expect(find.byKey(const Key('invoice_cancel_button')), findsNothing);
    expect(find.byKey(const Key('invoice_copy_address')), findsNothing);
    expect(find.byKey(const Key('invoice_countdown')), findsNothing);
    expect(find.text(_ar('pay.cancelled')), findsWidgets);
    expect((await repo.get(inv.id)).status, InvoiceStatus.failed);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('invoice: unknown id shows an error and retry loads it once it exists',
      (tester) async {
    final repo = MockPaymentsRepository(delayMs: 0);
    await pumpApp(
      tester,
      location: '/invoice/inv_mock_1',
      logicalSize: const Size(540, 2400),
      overrides: [paymentsRepositoryProvider.overrideWithValue(repo)],
    );
    expect(find.text(_ar('pay.err.not_found')), findsOneWidget);
    expect(find.byKey(const Key('invoice_disclaimer')), findsNothing);

    // The first mock invoice gets the id inv_mock_1.
    final created = repo.createSync(_deal, InvoiceKind.dealPayment);
    expect(created.id, 'inv_mock_1');
    await tester.tap(find.text(_ar('common.retry')));
    await settle(tester, frames: 6);
    expect(find.text(_ar('pay.err.not_found')), findsNothing);
    expect(find.byKey(const Key('invoice_disclaimer')), findsOneWidget);
    expect(find.byKey(const Key('invoice_copy_address')), findsOneWidget);
    expect(find.byKey(const Key('invoice_copy_memo')), findsOneWidget);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
