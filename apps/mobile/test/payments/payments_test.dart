import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/payments/payments_models.dart';
import 'package:factory_finder/features/payments/payments_repository.dart';
import 'package:factory_finder/features/payments/screens/invoice_screen.dart';
import 'package:factory_finder/features/payments/widgets/deal_payment_section.dart';
import 'package:factory_finder/features/payments/widgets/invoice_widgets.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
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

void main() {
  setUpWidgetTests();

  group('parsing', () {
    test('invoice json with every field', () {
      final inv = Invoice.fromJson({
        'id': 'inv_1',
        'deal_id': 'deal_1',
        'payer_user_id': 'u1',
        'payee': 'platform',
        'kind': 'commission',
        'amount': {'amount': '30.00', 'currency': 'USD'},
        'status': 'awaiting_payment',
        'expires_at': '2026-10-14T12:00:00Z',
        'provider': 'mock',
        'pay_address': 'TXyz',
        'pay_url': null,
        'pay_amount': {'amount': '30.000123', 'currency': 'USDT'},
        'memo': 'FF-1',
        'confirmations': 2,
        'paid_at': null,
        'created_at': '2026-10-14T11:00:00Z',
        'updated_at': '2026-10-14T11:00:00Z',
      });
      expect(inv.kind, InvoiceKind.commission);
      expect(inv.status, InvoiceStatus.awaitingPayment);
      expect(inv.amount.amount, '30.00');
      expect(inv.payAmount!.amount, '30.000123');
      expect(inv.payUrl, isNull);
      expect(inv.confirmations, 2);
      expect(inv.expiresAt, DateTime.utc(2026, 10, 14, 12));
    });

    test('tolerates missing fields and unknown enums', () {
      final inv = Invoice.fromJson({'id': 'x', 'status': 'weird', 'kind': 'zzz'});
      expect(inv.status, InvoiceStatus.unknown);
      expect(inv.kind, InvoiceKind.unknown);
      expect(inv.amount.amount, '0');
      expect(inv.confirmations, 0);
    });

    test('list accepts a page, a bare list and garbage', () {
      final row = {'id': 'a', 'status': 'paid'};
      expect(parseInvoiceList({'items': [row, 5]}).length, 1);
      expect(parseInvoiceList([row, row]).length, 2);
      expect(parseInvoiceList('nope'), isEmpty);
    });
  });

  group('status and countdown', () {
    test('status mapping', () {
      for (final s in InvoiceStatus.values) {
        expect(InvoiceStatus.parse(s.json), s);
      }
      expect(InvoiceStatus.parse(null), InvoiceStatus.unknown);
      expect(InvoiceStatus.awaitingPayment.isPollable, isTrue);
      expect(InvoiceStatus.confirming.isPollable, isTrue);
      expect(InvoiceStatus.paid.isPollable, isFalse);
      expect(InvoiceStatus.awaitingPayment.isCancellable, isTrue);
      expect(InvoiceStatus.confirming.isCancellable, isFalse);
      expect(invoiceStatusColor(InvoiceStatus.paid),
          isNot(invoiceStatusColor(InvoiceStatus.failed)));
    });

    test('time left clamps at zero and formats', () {
      final exp = DateTime.utc(2026, 10, 14, 12);
      expect(invoiceTimeLeft(exp, DateTime.utc(2026, 10, 14, 10, 58, 59)),
          const Duration(hours: 1, minutes: 1, seconds: 1));
      expect(invoiceTimeLeft(exp, DateTime.utc(2026, 10, 14, 13)), Duration.zero);
      expect(formatCountdown(const Duration(hours: 1, minutes: 1, seconds: 1)), '1:01:01');
      expect(formatCountdown(Duration.zero), '0:00:00');
      expect(formatCountdown(const Duration(hours: 30)), '30:00:00');
    });

    test('error mapping', () {
      ApiException e(int s) => ApiException(status: s, code: 'x', message: 'm');
      expect(invoiceErrorKey(e(404)), 'pay.err.not_found');
      expect(invoiceErrorKey(e(409)), 'pay.err.conflict');
      expect(invoiceErrorKey(e(503)), 'pay.err.provider_off');
      expect(invoiceErrorKey(e(500)), 'pay.err.generic');
      expect(invoiceErrorKey(StateError('x')), 'pay.err.generic');
    });
  });

  test('mock repo is idempotent, progresses to paid, and cancel rules hold', () async {
    final repo = MockPaymentsRepository(delayMs: 0);
    final a = repo.createSync(_deal, InvoiceKind.commission);
    final b = repo.createSync(_deal, InvoiceKind.commission);
    expect(b.id, a.id);
    expect(a.amount.amount, '30.00');
    final seen = <InvoiceStatus>[];
    for (var i = 0; i < 4; i++) {
      seen.add((await repo.get(a.id)).status);
    }
    expect(seen, [
      InvoiceStatus.awaitingPayment,
      InvoiceStatus.confirming,
      InvoiceStatus.confirming,
      InvoiceStatus.paid,
    ]);
    await expectLater(repo.cancel(a.id), throwsA(isA<ApiException>()));
    final c = repo.createSync(_deal, InvoiceKind.dealPayment);
    expect(c.amount.amount, '1000.00');
    expect((await repo.cancel(c.id)).status, InvoiceStatus.failed);
  });

  testWidgets('deal section lists invoices and creates one', (tester) async {
    final repo = MockPaymentsRepository(delayMs: 0);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [paymentsRepositoryProvider.overrideWithValue(repo)],
        child: MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: DealPaymentSection(deal: _deal)),
          ),
        ),
      ),
    );
    await settle(tester, frames: 3);
    expect(find.text('Commission & payment'), findsOneWidget);
    expect(find.text('No invoices for this deal yet.'), findsOneWidget);

    await tester.tap(find.byKey(const Key('create_commission_invoice')));
    await settle(tester, frames: 4);
    expect(find.text('Invoice created'), findsOneWidget);
    expect(find.text('Platform commission'), findsOneWidget);
    expect(find.text('Awaiting payment'), findsOneWidget);
    expect(find.text('No invoices for this deal yet.'), findsNothing);

    ScaffoldMessenger.of(tester.element(find.byType(Scaffold).first))
        .clearSnackBars();
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.takeException(), isNull);
  });

  testWidgets('invoice screen polls awaiting -> confirming -> paid', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final repo = MockPaymentsRepository(delayMs: 0);
    final inv = repo.createSync(_deal, InvoiceKind.commission);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [paymentsRepositoryProvider.overrideWithValue(repo)],
        child: MaterialApp(
          home: InvoiceScreen(
            invoiceId: inv.id,
            pollInterval: const Duration(seconds: 1),
          ),
        ),
      ),
    );
    await settle(tester, frames: 3);
    expect(find.text('Awaiting payment'), findsOneWidget);
    expect(find.byKey(const Key('invoice_countdown')), findsOneWidget);
    expect(find.byKey(const Key('invoice_copy_address')), findsOneWidget);
    expect(find.byKey(const Key('invoice_disclaimer')), findsOneWidget);
    expect(find.byKey(const Key('invoice_cancel_button')), findsOneWidget);

    await tester.pump(const Duration(seconds: 1));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Confirming'), findsOneWidget);
    expect(find.byKey(const Key('invoice_cancel_button')), findsNothing);

    await tester.pump(const Duration(seconds: 1));
    await tester.pump(const Duration(seconds: 1));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('Paid'), findsOneWidget);
    expect(find.byKey(const Key('invoice_copy_address')), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.takeException(), isNull);
  });
}
