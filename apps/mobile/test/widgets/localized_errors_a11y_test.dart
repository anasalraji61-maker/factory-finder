import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/deals/deals_repository.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_models.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_repository.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_screen.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:factory_finder/features/requests/screens/create_request_screen.dart';
import 'package:factory_finder/features/requests/screens/request_detail_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

class _FakeNotifyRepo implements NotifyPrefsRepository {
  _FakeNotifyRepo({this.error});
  final Object? error;

  @override
  Future<NotifyPrefs> get() async {
    final e = error;
    if (e != null) throw e;
    return const NotifyPrefs();
  }

  @override
  Future<NotifyPrefs> save(NotifyPrefs prefs, {String? digestEmail}) async => prefs;

  @override
  Future<NotifyPrefs> verifyEmail(String code) async => const NotifyPrefs();

  @override
  Future<NotifyPrefs> resendCode() async => const NotifyPrefs();
}

Future<void> _pump(
  WidgetTester tester,
  Widget home, {
  List<Override> overrides = const [],
  Locale locale = const Locale('ar'),
  double textScale = 1.0,
}) async {
  tester.view.physicalSize = const Size(360, 720);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        secureStoreProvider.overrideWithValue(MemoryStore()),
        ...overrides,
      ],
      child: MaterialApp(
        locale: locale,
        supportedLocales: const [Locale('ar'), Locale('en')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        builder: (context, c) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: TextScaler.linear(textScale)),
          child: c!,
        ),
        home: home,
      ),
    ),
  );
  await settle(tester);
}

void main() {
  setUpWidgetTests();

  group('localized backend errors', () {
    testWidgets('request detail shows the mapped message, not the raw one',
        (tester) async {
      final err = ApiException(
        status: 409,
        code: 'rating_too_early',
        message: 'raw backend text',
      );
      await _pump(
        tester,
        const RequestDetailScreen(requestId: 'r1'),
        overrides: [
          rfqDetailProvider.overrideWith(
              (ref, id) => Future<RfqRequest>.error(err)),
          rfqOffersProvider.overrideWith((ref, id) async => <Offer>[]),
          requestDealProvider.overrideWith((ref, id) async => null),
        ],
      );
      expect(find.text(AppStrings.lookup('ar', 'error.rating_too_early')),
          findsOneWidget);
      expect(find.text('raw backend text'), findsNothing);
      await tester.pumpWidget(const SizedBox.shrink());
    });

    testWidgets('notify prefs load error is localized per locale and falls back',
        (tester) async {
      await _pump(
        tester,
        const NotifyPrefsScreen(),
        locale: const Locale('en'),
        overrides: [
          notifyPrefsRepositoryProvider.overrideWithValue(_FakeNotifyRepo(
            error: ApiException(
                status: 409, code: 'conversation_full', message: 'raw full'),
          )),
        ],
      );
      expect(find.text(AppStrings.lookup('en', 'error.conversation_full')),
          findsOneWidget);
      expect(find.text('raw full'), findsNothing);

      // Unknown codes keep the backend message (behavior unchanged).
      await tester.pumpWidget(const SizedBox.shrink());
      await _pump(
        tester,
        const NotifyPrefsScreen(),
        overrides: [
          notifyPrefsRepositoryProvider.overrideWithValue(_FakeNotifyRepo(
            error: ApiException(
                status: 500, code: 'server_error', message: 'plain backend text'),
          )),
        ],
      );
      expect(find.text('plain backend text'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  });

  group('screen reader and 200% text scale', () {
    testWidgets('create request screen exposes its title and does not overflow',
        (tester) async {
      final handle = tester.ensureSemantics();
      await _pump(tester, const CreateRequestScreen(), textScale: 2.0);
      expect(tester.takeException(), isNull);
      expect(
        find.bySemanticsLabel(RegExp(AppStrings.lookup('ar', 'req.new'))),
        findsWidgets,
      );
      await tester.drag(find.byType(Scrollable).first, const Offset(0, -600));
      await settle(tester, frames: 3);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      handle.dispose();
    });

    testWidgets('notify prefs screen exposes its title and does not overflow',
        (tester) async {
      final handle = tester.ensureSemantics();
      await _pump(
        tester,
        const NotifyPrefsScreen(),
        textScale: 2.0,
        overrides: [
          notifyPrefsRepositoryProvider.overrideWithValue(_FakeNotifyRepo()),
        ],
      );
      expect(tester.takeException(), isNull);
      expect(
        find.bySemanticsLabel(
            RegExp(AppStrings.lookup('ar', 'notifyprefs.title'))),
        findsWidgets,
      );
      await tester.drag(find.byType(Scrollable).first, const Offset(0, -800));
      await settle(tester, frames: 3);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      handle.dispose();
    });
  });
}
