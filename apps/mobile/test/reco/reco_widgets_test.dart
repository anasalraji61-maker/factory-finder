import 'dart:convert';
import 'dart:io';

import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/reco/recently_viewed.dart';
import 'package:factory_finder/features/reco/reco_models.dart';
import 'package:factory_finder/features/reco/reco_repository.dart';
import 'package:factory_finder/features/reco/widgets/price_history_card.dart';
import 'package:factory_finder/features/reco/widgets/recent_settings.dart';
import 'package:factory_finder/features/reco/widgets/reco_carousel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

Map<String, dynamic> _obj(String name) => Map<String, dynamic>.from(
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync()) as Map);

class _FakeReco implements RecoRepository {
  _FakeReco({
    PriceHistory? history,
    RecoPage? similarPage,
    RecoPage? recoPage,
    this.failHistoryTimes = 0,
  })  : history = history ?? PriceHistory.fromJson(_obj('price_history')),
        similarPage = similarPage ?? RecoPage.fromJson(_obj('similar')),
        recoPage = recoPage ?? RecoPage.fromJson(_obj('recommendations'));

  final PriceHistory history;
  final RecoPage similarPage;
  final RecoPage recoPage;
  int failHistoryTimes;
  final List<int> historyDays = <int>[];

  @override
  Future<PriceHistory> priceHistory(String listingId, {int days = 90, PriceBucket? bucket}) async {
    historyDays.add(days);
    if (failHistoryTimes > 0) {
      failHistoryTimes--;
      throw ApiException(status: 500, code: 'server_error', message: 'boom');
    }
    return history;
  }

  @override
  Future<RecoPage> similar(String listingId, {int limit = 10}) async => similarPage;

  @override
  Future<RecoPage> recommendations({
    List<String> refs = const [],
    String? country,
    int limit = 20,
  }) async =>
      recoPage;
}

Future<void> _pumpHost(
  WidgetTester tester,
  Widget child, {
  required _FakeReco repo,
  Locale locale = const Locale('ar'),
  double textScale = 1.0,
  MemoryStore? store,
}) async {
  await tester.pumpWidget(const SizedBox.shrink()); // fresh tree for repeated calls
  tester.view.physicalSize = const Size(360, 720);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        recoRepositoryProvider.overrideWithValue(repo),
        keyValueStoreProvider.overrideWithValue(store ?? MemoryStore()),
      ],
      child: MaterialApp(
        locale: locale,
        supportedLocales: const [Locale('ar'), Locale('en')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        builder: (context, c) => MediaQuery(
          data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(textScale)),
          child: c!,
        ),
        home: Scaffold(body: SingleChildScrollView(child: child)),
      ),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

PriceHistory _history({
  bool synthetic = false,
  String direction = 'down',
  bool insufficient = false,
  bool withHints = true,
}) {
  final j = _obj('price_history');
  j['synthetic'] = synthetic;
  (j['trend'] as Map)['direction'] = direction;
  (j['trend'] as Map)['insufficient_data'] = insufficient;
  if (!withHints) j.remove('hints');
  return PriceHistory.fromJson(j);
}

void main() {
  setUpWidgetTests();

  group('price history card', () {
    testWidgets('chart, stats, trend badge and chart semantics at 360dp x2.0', (tester) async {
      final handle = tester.ensureSemantics();
      await _pumpHost(
        tester,
        const PriceHistoryCard(listingId: 'lst_0041'),
        repo: _FakeReco(),
        textScale: 2.0,
      );
      expect(find.byKey(const ValueKey<String>('price-chart')), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('price-stats')), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('price-trend-down')), findsOneWidget);
      expect(find.byIcon(Icons.trending_down), findsOneWidget);
      expect(find.text('انخفاض'), findsOneWidget);
      expect(find.text('-9.4%'), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('price-synthetic-note')), findsNothing);
      expect(find.bySemanticsLabel(RegExp('مخطط سعر')), findsOneWidget);
      expect(tester.takeException(), isNull);
      handle.dispose();
    });

    testWidgets('trend colour and icon differ per direction', (tester) async {
      for (final entry in <String, IconData>{
        'up': Icons.trending_up,
        'flat': Icons.trending_flat,
      }.entries) {
        await _pumpHost(
          tester,
          const PriceHistoryCard(listingId: 'x'),
          repo: _FakeReco(history: _history(direction: entry.key)),
          locale: const Locale('en'),
        );
        expect(find.byKey(ValueKey<String>('price-trend-${entry.key}')), findsOneWidget);
        expect(find.byIcon(entry.value), findsOneWidget);
        expect(tester.takeException(), isNull);
      }
      expect(
        trendStyle(PriceDirection.up, Brightness.light).color,
        isNot(trendStyle(PriceDirection.down, Brightness.light).color),
      );
    });

    testWidgets('synthetic data carries the estimate note', (tester) async {
      await _pumpHost(
        tester,
        const PriceHistoryCard(listingId: 'x'),
        repo: _FakeReco(history: _history(synthetic: true)),
        locale: const Locale('en'),
      );
      expect(find.byKey(const ValueKey<String>('price-synthetic-note')), findsOneWidget);
      expect(find.textContaining('Estimated'), findsOneWidget);
    });

    testWidgets('insufficient data: message only, no chart, no alert button', (tester) async {
      await _pumpHost(
        tester,
        PriceHistoryCard(listingId: 'x', onAlertSuggested: (_) {}),
        repo: _FakeReco(
          history: PriceHistory.fromJson(_obj('price_history_insufficient')),
        ),
        textScale: 2.0,
      );
      expect(find.byKey(const ValueKey<String>('price-insufficient')), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('price-chart')), findsNothing);
      expect(find.byKey(const ValueKey<String>('price-alert-suggested')), findsNothing);
      expect(find.byKey(const ValueKey<String>('price-synthetic-note')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('range chips reload with the chosen number of days', (tester) async {
      final repo = _FakeReco();
      await _pumpHost(tester, const PriceHistoryCard(listingId: 'x'), repo: repo);
      expect(repo.historyDays, [90]);
      await tester.tap(find.byKey(const ValueKey<String>('price-range-30')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      await tester.tap(find.byKey(const ValueKey<String>('price-range-365')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(repo.historyDays, [90, 30, 365]);
      final chip = tester.widget<ChoiceChip>(find.byKey(const ValueKey<String>('price-range-365')));
      expect(chip.selected, isTrue);
      expect(tester.takeException(), isNull);
    });

    testWidgets('alert button hands over the suggested target', (tester) async {
      Money? got;
      await _pumpHost(
        tester,
        PriceHistoryCard(listingId: 'x', onAlertSuggested: (m) => got = m),
        repo: _FakeReco(),
        textScale: 2.0,
      );
      final button = find.byKey(const ValueKey<String>('price-alert-suggested'));
      await tester.ensureVisible(button);
      await tester.pump();
      await tester.tap(button);
      expect(got?.amount, '2.76');
      expect(got?.currency, 'USD');
      expect(tester.takeException(), isNull);
    });

    testWidgets('no alert button without a callback or hints', (tester) async {
      await _pumpHost(
        tester,
        const PriceHistoryCard(listingId: 'x'),
        repo: _FakeReco(),
      );
      expect(find.byKey(const ValueKey<String>('price-alert-suggested')), findsNothing);
      await _pumpHost(
        tester,
        PriceHistoryCard(listingId: 'y', onAlertSuggested: (_) {}),
        repo: _FakeReco(history: _history(withHints: false)),
      );
      expect(find.byKey(const ValueKey<String>('price-alert-suggested')), findsNothing);
    });

    testWidgets('load error offers a retry that succeeds', (tester) async {
      final repo = _FakeReco(failHistoryTimes: 1);
      await _pumpHost(tester, const PriceHistoryCard(listingId: 'x'), repo: repo);
      expect(find.byKey(const ValueKey<String>('price-history-error')), findsOneWidget);
      await tester.tap(find.text('إعادة المحاولة'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.byKey(const ValueKey<String>('price-chart')), findsOneWidget);
      expect(repo.historyDays, [90, 90]);
      expect(tester.takeException(), isNull);
    });
  });

  group('similar and recommended rows', () {
    testWidgets('similar row shows reasons in Arabic and English', (tester) async {
      await _pumpHost(
        tester,
        const SimilarListingsSection(listingId: 'lst_0041'),
        repo: _FakeReco(),
      );
      expect(find.byKey(const ValueKey<String>('similar-section')), findsOneWidget);
      expect(find.text('منتجات مشابهة'), findsOneWidget);
      expect(find.text('نفس الفئة'), findsOneWidget);
      expect(find.text('Same category'), findsNothing);

      await _pumpHost(
        tester,
        const SimilarListingsSection(listingId: 'lst_0041'),
        repo: _FakeReco(),
        locale: const Locale('en'),
      );
      expect(find.text('Similar listings'), findsOneWidget);
      expect(find.text('Same category'), findsOneWidget);
      expect(find.text('نفس الفئة'), findsNothing);
      // At most two chips per card.
      expect(find.text('Trusted supplier'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('rows survive 360dp at text scale 2.0 and horizontal scrolling', (tester) async {
      await _pumpHost(
        tester,
        const Column(children: [SimilarListingsSection(listingId: 'a'), RecommendedSection()]),
        repo: _FakeReco(),
        textScale: 2.0,
      );
      expect(tester.takeException(), isNull);
      final lists = find.descendant(
        of: find.byKey(const ValueKey<String>('similar-section')),
        matching: find.byType(ListView),
      );
      await tester.drag(lists, const Offset(-300, 0));
      await tester.pump();
      expect(find.byKey(const ValueKey<String>('recommended-section')), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('empty results render nothing', (tester) async {
      await _pumpHost(
        tester,
        const Column(children: [SimilarListingsSection(listingId: 'a'), RecommendedSection()]),
        repo: _FakeReco(similarPage: const RecoPage(), recoPage: const RecoPage()),
      );
      expect(find.byKey(const ValueKey<String>('similar-section')), findsNothing);
      expect(find.byKey(const ValueKey<String>('recommended-section')), findsNothing);
    });
  });

  group('recently viewed settings', () {
    testWidgets('the clear button empties the local history', (tester) async {
      final store = MemoryStore({kRecentlyViewedKey: '["a","b"]'});
      await _pumpHost(
        tester,
        const RecentlyViewedSettings(),
        repo: _FakeReco(),
        textScale: 2.0,
        store: store,
      );
      final container = ProviderScope.containerOf(
        tester.element(find.byType(RecentlyViewedSettings)),
      );
      await tester.runAsync(() => container.read(recentlyViewedProvider.notifier).ready);
      await tester.pump(); // the stored ids finish loading
      expect(container.read(recentlyViewedProvider).ids, ['a', 'b']);

      final button = find.byKey(const ValueKey<String>('settings-clear-recent'));
      await tester.ensureVisible(button);
      await tester.pump();
      await tester.tap(button);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(container.read(recentlyViewedProvider).ids, isEmpty);
      expect(store.data.containsKey(kRecentlyViewedKey), isFalse);
      expect(find.text('تم مسح المشاهدات الأخيرة'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('in the app (mock mode)', () {
    testWidgets('listing detail records the view and prefills the alert sheet', (tester) async {
      await pumpApp(
        tester,
        location: '/listing/lst_001',
        logicalSize: const Size(360, 720),
      );
      await settle(tester, frames: 6);
      final container = ProviderScope.containerOf(tester.element(find.byType(FactoryFinderApp)));
      expect(container.read(recentlyViewedProvider).ids, contains('lst_001'));

      final scrollable = find.byWidgetPredicate(
        (w) => w is Scrollable && w.axisDirection == AxisDirection.down,
      );
      final button = find.byKey(const ValueKey<String>('price-alert-suggested'));
      for (var i = 0; i < 12; i++) {
        if (tester.any(button) &&
            tester.getCenter(button).dy < 520 &&
            tester.getCenter(button).dy > 60) {
          break;
        }
        await tester.drag(scrollable.first, const Offset(0, -300));
        await tester.pump();
      }
      expect(button, findsOneWidget);
      await tester.tap(button);
      await settle(tester, frames: 4);

      expect(find.text('ابدأ المتابعة'), findsOneWidget);
      final field = tester.widget<TextField>(find.byType(TextField).first);
      final prefilled = double.tryParse(field.controller!.text);
      expect(prefilled, isNotNull);
      expect(prefilled! > 0, isTrue);
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });

    testWidgets('discover shows the recommended section at 360dp x2.0', (tester) async {
      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await pumpApp(tester, location: '/discover', logicalSize: const Size(360, 720));
      await settle(tester, frames: 6);
      final scrollable = find.byWidgetPredicate(
        (w) => w is Scrollable && w.axisDirection == AxisDirection.down,
      );
      for (var i = 0; i < 6 && !tester.any(find.text('موصى به لك')); i++) {
        await tester.drag(scrollable.first, const Offset(0, -500));
        await tester.pump();
      }
      expect(find.text('موصى به لك'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });
  });
}
