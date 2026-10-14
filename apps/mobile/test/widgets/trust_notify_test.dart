import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/trust/trust_models.dart';
import 'package:factory_finder/features/trust/trust_repository.dart';
import 'package:factory_finder/features/trust/trust_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

class _FakeTrustRepo implements TrustExtrasRepository {
  int calls = 0;

  @override
  Future<List<TrustHistoryPoint>> history(String supplierId) async =>
      const <TrustHistoryPoint>[];

  @override
  Future<ReportResult> report(String supplierId, String type, String text) async {
    calls++;
    if (calls == 1) {
      throw ApiException(status: 429, code: 'rate_limited', message: 'slow');
    }
    return const ReportResult(id: 'r1', status: 'pending_review');
  }
}

void main() {
  setUpWidgetTests();

  testWidgets('supplier screen shows confidence, missing info and history fallback',
      (tester) async {
    await pumpApp(tester, location: '/supplier/sup_cn_004');
    await settle(tester, frames: 8);

    expect(find.text('مستوى الثقة بالتقييم'), findsOneWidget);
    expect(find.byKey(const Key('trust_confidence_meter')), findsOneWidget);
    expect(find.text('معلومات ناقصة'), findsOneWidget);
    expect(find.text('تدقيق مصنع من طرف ثالث'), findsOneWidget);
    expect(find.byKey(const Key('trust_history_chart')), findsOneWidget);

    // Guests get a sign-in hint instead of the report sheet.
    await tester.tap(find.byKey(const Key('trust_report_button')));
    await settle(tester, frames: 3);
    expect(find.text('سجّل الدخول لإرسال بلاغ'), findsOneWidget);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('report sheet validates, shows 429, then success', (tester) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final repo = _FakeTrustRepo();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [trustExtrasRepositoryProvider.overrideWithValue(repo)],
        child: const MaterialApp(
          home: Scaffold(body: ReportConcernSheet(supplierId: 'sup_x')),
        ),
      ),
    );
    await settle(tester, frames: 2);

    await tester.tap(find.text('Submit report'));
    await settle(tester, frames: 2);
    expect(find.text('Choose a type of concern'), findsOneWidget);
    expect(repo.calls, 0);

    await tester.tap(find.byKey(const Key('trust_report_type')));
    await settle(tester, frames: 3);
    await tester.tap(find.text('Fraud').last);
    await settle(tester, frames: 3);

    await tester.tap(find.text('Submit report'));
    await settle(tester, frames: 2);
    expect(find.text('Describe the concern'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('trust_report_text')), 'Took my deposit');
    await tester.tap(find.text('Submit report'));
    await settle(tester, frames: 3);
    expect(
      find.text('You have sent too many reports. Please try again later.'),
      findsOneWidget,
    );

    await tester.tap(find.text('Submit report'));
    await settle(tester, frames: 3);
    expect(find.byKey(const Key('trust_report_success')), findsOneWidget);
    expect(repo.calls, 2);

    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('notification prefs: edit, invalid email, save', (tester) async {
    await pumpApp(tester, location: '/notification-prefs');
    await settle(tester, frames: 6);

    final push = find.byKey(const Key('np_price_drop_push'));
    expect(tester.widget<SwitchListTile>(push).value, isTrue);
    await tester.tap(push);
    await settle(tester, frames: 2);
    expect(tester.widget<SwitchListTile>(push).value, isFalse);

    final list = find.byType(Scrollable).first;
    await tester.scrollUntilVisible(find.byKey(const Key('np_email')), 300,
        scrollable: list);
    await tester.enterText(find.byKey(const Key('np_email')), 'not-an-email');
    await tester.scrollUntilVisible(find.text('حفظ التغييرات'), 300, scrollable: list);
    await tester.tap(find.text('حفظ التغييرات'));
    await settle(tester, frames: 3);
    expect(find.text('أدخل بريداً إلكترونياً صحيحاً'), findsOneWidget);
    expect(find.byKey(const Key('np_saved')), findsNothing);

    await tester.scrollUntilVisible(find.byKey(const Key('np_email')), -300,
        scrollable: list);
    await tester.enterText(find.byKey(const Key('np_email')), 'me@example.com');
    await tester.scrollUntilVisible(find.text('حفظ التغييرات'), 300, scrollable: list);
    await tester.tap(find.text('حفظ التغييرات'));
    await settle(tester, frames: 6);
    await tester.scrollUntilVisible(find.byKey(const Key('np_saved')), 300, scrollable: list);
    expect(find.byKey(const Key('np_saved')), findsOneWidget);

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('alerts inbox: shipment alert deep-links to tracking detail',
      (tester) async {
    final router = await pumpApp(tester, location: '/alerts');
    await settle(tester, frames: 6);

    expect(find.byKey(const Key('alert_icon_shipment_status')), findsOneWidget);
    expect(find.byKey(const Key('alert_icon_shipment_delayed')), findsOneWidget);
    expect(find.text('تأخّر الشحنة'), findsOneWidget);

    await tester.tap(find.text('تحديث الشحنة'));
    await settle(tester, frames: 8);
    expect(router.routerDelegate.currentConfiguration.uri.path,
        '/logistics/tracking/shp_001');

    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
