import 'dart:convert';
import 'dart:io';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/analytics/analytics_logic.dart';
import 'package:factory_finder/features/analytics/analytics_models.dart';
import 'package:factory_finder/features/analytics/analytics_repository.dart';
import 'package:factory_finder/features/analytics/screens/supplier_analytics_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../widgets/test_app.dart';

typedef _Handler = Future<SupplierAnalytics> Function(int days, String? listingId);

class _FakeRepo extends AnalyticsRepository {
  _FakeRepo(this.handler)
      : super(ApiClient(baseUrl: 'http://unused.invalid', isMock: true));

  final _Handler handler;
  final List<(int, String?)> calls = <(int, String?)>[];

  @override
  Future<SupplierAnalytics> fetch({
    int days = kDefaultAnalyticsDays,
    String? listingId,
  }) {
    calls.add((days, listingId));
    return handler(days, listingId);
  }
}

SupplierAnalytics _fixture() => SupplierAnalytics.fromJson(
      jsonDecode(File('test/fixtures/analytics/analytics_7d.json').readAsStringSync()),
    );

const SupplierAnalytics _empty = SupplierAnalytics(
  period: AnalyticsPeriod(days: 30, from: '2026-09-16', to: '2026-10-15'),
  totals: AnalyticsCounts.zero,
  previousTotals: AnalyticsCounts.zero,
);

Future<GoRouter> _pump(
  WidgetTester tester,
  _FakeRepo repo, {
  Locale locale = const Locale('en'),
  double textScale = 1.0,
  String? initialListingId,
}) async {
  tester.view.physicalSize = const Size(360, 4000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final router = GoRouter(
    routes: <RouteBase>[
      GoRoute(
        path: '/',
        builder: (context, state) =>
            SupplierAnalyticsScreen(initialListingId: initialListingId),
      ),
      GoRoute(
        path: '/my-products/:id',
        builder: (context, state) => Scaffold(
          body: Text('editor ${state.pathParameters['id']}'),
        ),
      ),
    ],
  );
  await tester.pumpWidget(
    ProviderScope(
      overrides: [analyticsRepositoryProvider.overrideWithValue(repo)],
      child: MaterialApp.router(
        routerConfig: router,
        locale: locale,
        supportedLocales: const [Locale('ar'), Locale('en')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: TextScaler.linear(textScale)),
          child: child!,
        ),
      ),
    ),
  );
  await settle(tester);
  return router;
}

Finder _key(String k) => find.byKey(ValueKey<String>(k));

void main() {
  setUpWidgetTests();

  testWidgets('loads, shows KPIs, funnel, chart and top listings (360dp)', (tester) async {
    final repo = _FakeRepo((d, l) async => _fixture());
    await _pump(tester, repo);

    expect(repo.calls, <(int, String?)>[(30, null)]);
    expect(tester.takeException(), isNull);

    expect(find.descendant(of: _key('ana-kpi-view'), matching: find.text('120')),
        findsOneWidget);
    expect(find.descendant(of: _key('ana-kpi-impression'), matching: find.text('420')),
        findsOneWidget);
    expect(_key('ana-chart'), findsOneWidget);
    expect(_key('ana-funnel'), findsOneWidget);
    expect(find.text('View to contact: 20.8%'), findsOneWidget);
    expect(find.text('Impression to view: 28.6%'), findsOneWidget);
    expect(_key('ana-row-lst_a'), findsOneWidget);
    expect(find.text('Showing 2 of 3 products with activity'), findsOneWidget);
    expect(find.text('2026-10-09 to 2026-10-15'), findsOneWidget);

    // chart painter has a semantics label
    expect(
      find.byWidgetPredicate((w) =>
          w is Semantics &&
          (w.properties.label ?? '').startsWith('Views: total 120, peak 30')),
      findsOneWidget,
    );
  });

  testWidgets('change chips combine icon, sign and colour', (tester) async {
    await _pump(tester, _FakeRepo((d, l) async => _fixture()));

    Finder chip(String metric) =>
        find.descendant(of: _key('ana-kpi-$metric'), matching: find.byType(ChangeChip));

    // views +50% (good = green, up arrow)
    expect(find.descendant(of: chip('view'), matching: find.text('+50%')), findsOneWidget);
    final up = tester.widget<Icon>(
        find.descendant(of: chip('view'), matching: find.byType(Icon)));
    expect(up.icon, Icons.arrow_upward);
    expect(up.color, const Color(0xFF15803D));

    // reports -50%: down arrow but GOOD (green) because fewer reports is better
    expect(find.descendant(of: chip('report'), matching: find.text('-50%')), findsOneWidget);
    final down = tester.widget<Icon>(
        find.descendant(of: chip('report'), matching: find.byType(Icon)));
    expect(down.icon, Icons.arrow_downward);
    expect(down.color, const Color(0xFF15803D));

    // contact clicks: previous was 0 -> no comparison
    expect(find.descendant(of: chip('contact_click'), matching: find.text('-')),
        findsOneWidget);
  });

  testWidgets('a decrease in a normal metric is red with a down arrow', (tester) async {
    final decreased = SupplierAnalytics.fromJson(<String, dynamic>{
      'totals': <String, dynamic>{'view': 5},
      'previous_totals': <String, dynamic>{'view': 10},
      'change_pct': <String, dynamic>{'view': -50.0},
    });
    await _pump(tester, _FakeRepo((d, l) async => decreased));
    final chip = find.descendant(
        of: _key('ana-kpi-view'), matching: find.byType(ChangeChip));
    expect(find.descendant(of: chip, matching: find.text('-50%')), findsOneWidget);
    final red = tester.widget<Icon>(
        find.descendant(of: chip, matching: find.byType(Icon)));
    expect(red.icon, Icons.arrow_downward);
    expect(red.color, const Color(0xFFB91C1C));
  });

  testWidgets('period chips reload with the chosen days', (tester) async {
    final repo = _FakeRepo((d, l) async => _fixture());
    await _pump(tester, repo);

    await tester.tap(_key('ana-period-7'));
    await settle(tester);
    await tester.tap(_key('ana-period-90'));
    await settle(tester);
    await tester.tap(_key('ana-period-90')); // already selected: no reload
    await settle(tester);

    expect(repo.calls.map((c) => c.$1).toList(), <int>[30, 7, 90]);
  });

  testWidgets('metric chips switch the chart label', (tester) async {
    await _pump(tester, _FakeRepo((d, l) async => _fixture()));
    await tester.tap(_key('ana-metric-impression'));
    await settle(tester, frames: 2);
    expect(
      find.byWidgetPredicate((w) =>
          w is Semantics &&
          (w.properties.label ?? '').startsWith('Impressions: total 420')),
      findsOneWidget,
    );
  });

  testWidgets('filter sheet narrows to one listing and can be cleared', (tester) async {
    final repo = _FakeRepo((d, l) async => _fixture());
    await _pump(tester, repo);

    await tester.tap(_key('ana-filter'));
    await settle(tester, frames: 4);
    expect(_key('ana-filter-opt-all'), findsOneWidget);
    await tester.tap(_key('ana-filter-opt-lst_b'));
    await settle(tester);
    expect(repo.calls.last, (30, 'lst_b'));
    expect(find.descendant(of: _key('ana-filter'), matching: find.text('Solar inverter')),
        findsOneWidget);

    await tester.tap(_key('ana-filter'));
    await settle(tester, frames: 4);
    await tester.tap(_key('ana-filter-opt-all'));
    await settle(tester);
    expect(repo.calls.last, (30, null));
  });

  testWidgets('initial listing id is passed to the first request', (tester) async {
    final repo = _FakeRepo((d, l) async => _fixture());
    await _pump(tester, repo, initialListingId: 'lst_a');
    expect(repo.calls.first, (30, 'lst_a'));
  });

  testWidgets('tapping a top listing opens its editor', (tester) async {
    await _pump(tester, _FakeRepo((d, l) async => _fixture()));
    await tester.tap(_key('ana-row-lst_b'));
    await settle(tester);
    expect(find.text('editor lst_b'), findsOneWidget);
  });

  testWidgets('empty state', (tester) async {
    await _pump(tester, _FakeRepo((d, l) async => _empty));
    expect(find.text('No activity in this period'), findsOneWidget);
    expect(_key('ana-chart'), findsNothing);
    // controls stay available so the period / filter can be changed
    expect(_key('ana-period-7'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('error state with retry, then success', (tester) async {
    var fail = true;
    final repo = _FakeRepo((d, l) async {
      if (fail) {
        throw ApiException(status: 403, code: 'supplier_required', message: 'no');
      }
      return _fixture();
    });
    await _pump(tester, repo);
    expect(find.text('Analytics are only available to verified suppliers.'),
        findsOneWidget);

    fail = false;
    await tester.tap(find.text('Retry'));
    await settle(tester);
    expect(repo.calls, hasLength(2));
    expect(_key('ana-kpi-view'), findsOneWidget);
  });

  testWidgets('404 for a foreign listing shows a clear message', (tester) async {
    final repo = _FakeRepo((d, l) async {
      throw ApiException(status: 404, code: 'not_found', message: 'x');
    });
    await _pump(tester, repo, initialListingId: 'other');
    expect(find.text('That product is not one of your listings.'), findsOneWidget);
  });

  testWidgets('loading state shows while the request is pending', (tester) async {
    final repo = _FakeRepo(
      (d, l) => Future<SupplierAnalytics>.delayed(const Duration(days: 1), _fixture),
    );
    tester.view.physicalSize = const Size(360, 4000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [analyticsRepositoryProvider.overrideWithValue(repo)],
        child: const MaterialApp(
          locale: Locale('en'),
          supportedLocales: [Locale('ar'), Locale('en')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          home: SupplierAnalyticsScreen(),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.byType(LoadingList), findsOneWidget);
    expect(_key('ana-kpi-view'), findsNothing);
    expect(_key('ana-period-30'), findsOneWidget);
    // unmount, then let the pending timer fire so no timer is left behind
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(days: 2));
  });

  for (final locale in const [Locale('ar'), Locale('en')]) {
    testWidgets('no overflow at 360dp and text scale 2.0 (${locale.languageCode})',
        (tester) async {
      final long = SupplierAnalytics.fromJson(<String, dynamic>{
        ...jsonDecode(File('test/fixtures/analytics/analytics_7d.json').readAsStringSync())
            as Map<String, dynamic>,
        'listings': <dynamic>[
          <String, dynamic>{
            'listing_id': 'lst_long',
            'title': 'A very long listing title for a hydraulic injection moulding '
                'machine with servo drive and spare moulds included',
            'status': 'published',
            'view': 1234567,
            'contact_click': 12345,
            'view_to_contact': 0.01,
          },
        ],
        'totals': <String, dynamic>{
          'impression': 98765432,
          'view': 1234567,
          'contact_click': 12345,
        },
      });
      await _pump(tester, _FakeRepo((d, l) async => long),
          locale: locale, textScale: 2.0);
      expect(tester.takeException(), isNull);
      expect(_key('ana-row-lst_long'), findsOneWidget);

      await tester.tap(_key('ana-filter'));
      await settle(tester, frames: 4);
      expect(tester.takeException(), isNull);
    });
  }
}
