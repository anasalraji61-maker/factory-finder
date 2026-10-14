import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/freight/data/freight_drafts.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/data/freight_prefill.dart';
import 'package:factory_finder/features/freight/data/freight_repository.dart';
import 'package:factory_finder/features/freight/data/mock_freight_repository.dart';
import 'package:factory_finder/features/freight/freight_routes.dart';
import 'package:factory_finder/features/freight/widgets/report_sheet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../widgets/test_app.dart';

ValueKey<String> k(String id) => ValueKey<String>(id);

DateTime _clock() => DateTime.utc(2026, 10, 15, 12);

const QuoteDraft _tinyQuote = QuoteDraft(amount: '5', currency: 'USD', transitDays: 3);

const ApplicationDraft _application = ApplicationDraft(
  companyName: 'Test Freight',
  countryCode: 'CN',
  lanes: [Lane(origin: 'CN', destination: 'IQ')],
  modes: ['sea'],
  incoterms: ['FOB'],
);

class _AcceptFails extends MockFreightRepository {
  _AcceptFails() : super(clock: _clock);

  @override
  Future<AcceptResult> acceptQuote(String quoteId) async => throw ApiException(
        status: 409,
        code: 'already_awarded',
        message: 'already_awarded',
      );
}

class _Flaky extends MockFreightRepository {
  _Flaky() : super(clock: _clock);

  bool fail = true;

  @override
  Future<FreightPage<ShipmentRequest>> myRequests({
    String? status,
    String? cursor,
    int limit = 20,
  }) {
    if (fail) {
      return Future<FreightPage<ShipmentRequest>>.error(ApiException(
        status: 429,
        code: 'rate_limited',
        message: 'slow down',
        retryAfterSeconds: 30,
      ));
    }
    return super.myRequests(status: status, cursor: cursor, limit: 2);
  }
}

/// Pumps the freight routes (mounted under /logistics like the app) and
/// navigates to [location].
Future<GoRouter> _pump(
  WidgetTester tester,
  String location,
  FreightRepository repo, {
  FreightPrefill? prefill,
  Locale locale = const Locale('en'),
  Size size = const Size(400, 3000),
  double textScale = 1.0,
}) async {
  tester.view.physicalSize = size * 2.0;
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  tester.platformDispatcher.textScaleFactorTestValue = textScale;
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);

  final router = GoRouter(
    initialLocation: '/logistics',
    routes: [
      GoRoute(
        path: '/logistics',
        builder: (context, state) => const Scaffold(body: Text('logistics home')),
        routes: [freightRoute],
      ),
    ],
  );
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        freightRepositoryProvider.overrideWithValue(repo),
        if (prefill != null) freightPrefillProvider.overrideWith((ref) => prefill),
      ],
      child: MaterialApp.router(
        routerConfig: router,
        locale: locale,
        supportedLocales: const [Locale('ar'), Locale('en')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
      ),
    ),
  );
  await settle(tester, frames: 3);
  router.go(location);
  await settle(tester);
  return router;
}

Future<void> _dispose(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(milliseconds: 100));
  expect(tester.takeException(), isNull);
}

Future<void> _tap(WidgetTester tester, String id) async {
  await tester.tap(find.byKey(k(id)));
  await settle(tester);
}

double _top(WidgetTester tester, String id) => tester.getTopLeft(find.byKey(k(id))).dy;

void main() {
  setUpWidgetTests();

  group('buyer: create request', () {
    testWidgets('prefilled form validates, submits and opens the request', (tester) async {
      final repo = MockFreightRepository();
      await _pump(
        tester,
        '/logistics/freight/new',
        repo,
        prefill: const FreightPrefill(
          originCountry: 'CN',
          originPlace: 'Shenzhen',
          destinationCountry: 'IQ',
          destinationPlace: 'Baghdad',
          mode: 'sea',
          containerType: '40HC',
          incoterm: 'CIF',
          weightKg: '18000',
          volumeCbm: '58.5',
          landedCostRef: 'q_123',
        ),
      );
      expect(find.text('Prefilled from the cost calculator'), findsOneWidget);

      // Cargo is required: the form shows a localized error and sends nothing.
      await _tap(tester, 'freight_submit_request');
      expect(find.text('Describe the cargo in 3 to 500 characters.'), findsOneWidget);
      expect((await repo.myRequests()).items, hasLength(3));

      await tester.enterText(find.byKey(k('freight_cargo')), 'LED lighting, palletized');
      await _tap(tester, 'freight_submit_request');

      final mine = (await repo.myRequests()).items;
      expect(mine, hasLength(4));
      final created = mine.firstWhere((r) => r.cargoDescription == 'LED lighting, palletized');
      expect(created.weightKg, '18000.000');
      expect(created.volumeCbm, '58.500');
      expect(created.containerType, '40HC');
      expect(created.incoterm, 'CIF');
      expect(created.landedCostRef, 'q_123');
      expect(created.originPlace, 'Shenzhen');
      // Detail screen of the new request is shown.
      expect(find.byKey(k('freight_summary')), findsOneWidget);
      expect(find.byKey(k('freight_no_quotes')), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('server errors are mapped, not echoed', (tester) async {
      final repo = MockFreightRepository();
      await _pump(tester, '/logistics/freight/new', repo);
      await tester.enterText(find.byKey(k('freight_origin_place')), 'Ningbo');
      await tester.enterText(find.byKey(k('freight_dest_place')), 'Basra');
      await tester.enterText(find.byKey(k('freight_weight')), '500');
      await tester.enterText(find.byKey(k('freight_cargo')), 'details at http://x.example');
      await _tap(tester, 'freight_submit_request');
      expect(find.byKey(k('freight_form_error')), findsOneWidget);
      expect(find.textContaining('prohibited goods. Edit it'), findsOneWidget);
      expect((await repo.myRequests()).items, hasLength(3));
      await _dispose(tester);
    });

    testWidgets('weight or volume is required; 4 decimals rejected', (tester) async {
      final repo = MockFreightRepository();
      await _pump(tester, '/logistics/freight/new', repo);
      await tester.enterText(find.byKey(k('freight_origin_place')), 'Ningbo');
      await tester.enterText(find.byKey(k('freight_dest_place')), 'Basra');
      await tester.enterText(find.byKey(k('freight_cargo')), 'Steel pipes');
      await _tap(tester, 'freight_submit_request');
      expect(find.text('Enter at least the weight or the volume.'), findsWidgets);
      await tester.enterText(find.byKey(k('freight_weight')), '1.2345');
      await _tap(tester, 'freight_submit_request');
      expect(find.text('Enter a positive number with at most 3 decimals.'), findsWidgets);
      await _dispose(tester);
    });

    testWidgets('Arabic locale and 2.0 text scale at 360dp do not overflow', (tester) async {
      final repo = MockFreightRepository();
      await _pump(
        tester,
        '/logistics/freight/new',
        repo,
        locale: const Locale('ar'),
        size: const Size(360, 800),
        textScale: 2.0,
        prefill: const FreightPrefill(originCountry: 'CN', destinationCountry: 'IQ', mode: 'sea', containerType: '20GP'),
      );
      expect(find.text('طلب عروض شحن جديد'), findsWidgets);
      for (var i = 0; i < 8; i++) {
        await tester.drag(find.byType(ListView).first, const Offset(0, -500));
        await settle(tester, frames: 2);
      }
      expect(tester.takeException(), isNull);
      await _dispose(tester);
    });
  });

  group('buyer: list and detail', () {
    testWidgets('list shows requests, paginates and filters', (tester) async {
      final repo = _Flaky()..fail = false;
      await _pump(tester, '/logistics/freight', repo);
      expect(find.byKey(k('freight_request_fr_100')), findsOneWidget);
      expect(find.byKey(k('freight_request_fr_102')), findsOneWidget);
      expect(find.byKey(k('freight_request_fr_101')), findsNothing);
      await _tap(tester, 'freight_requests_load_more');
      expect(find.byKey(k('freight_request_fr_101')), findsOneWidget);
      expect(find.byKey(k('freight_requests_load_more')), findsNothing);
      await _tap(tester, 'freight_filter_awarded');
      expect(find.byKey(k('freight_request_fr_102')), findsOneWidget);
      expect(find.byKey(k('freight_request_fr_100')), findsNothing);
      await _tap(tester, 'freight_filter_expired');
      expect(find.byKey(k('freight_requests_empty')), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('429 with Retry-After shows a localized message and retries', (tester) async {
      final repo = _Flaky();
      await _pump(tester, '/logistics/freight', repo);
      expect(find.byKey(k('freight_requests_error')), findsOneWidget);
      expect(find.text('Too many attempts. Try again in 30 seconds.'), findsOneWidget);
      repo.fail = false;
      await tester.tap(find.text('Retry'));
      await settle(tester);
      expect(find.byKey(k('freight_requests_error')), findsNothing);
      expect(find.byKey(k('freight_request_fr_100')), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('comparison cards sort by price, transit, rating and score', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await _pump(tester, '/logistics/freight/requests/fr_100', repo);
      for (final id in ['fq_100_1', 'fq_100_2', 'fq_100_3']) {
        expect(find.byKey(k('freight_accept_$id')), findsOneWidget);
      }
      // default: score order A (89.5), B (86.5), C (84.1)
      expect(_top(tester, 'freight_accept_fq_100_1'), lessThan(_top(tester, 'freight_accept_fq_100_2')));
      expect(_top(tester, 'freight_accept_fq_100_2'), lessThan(_top(tester, 'freight_accept_fq_100_3')));
      expect(find.text('Score 89.5'), findsOneWidget);
      expect(find.text('Top rated'), findsWidgets);

      await _tap(tester, 'freight_sort_price');
      expect(_top(tester, 'freight_accept_fq_100_2'), lessThan(_top(tester, 'freight_accept_fq_100_1')));
      expect(_top(tester, 'freight_accept_fq_100_1'), lessThan(_top(tester, 'freight_accept_fq_100_3')));

      await _tap(tester, 'freight_sort_transit');
      expect(_top(tester, 'freight_accept_fq_100_3'), lessThan(_top(tester, 'freight_accept_fq_100_1')));
      expect(_top(tester, 'freight_accept_fq_100_1'), lessThan(_top(tester, 'freight_accept_fq_100_2')));

      await _tap(tester, 'freight_sort_rating');
      expect(_top(tester, 'freight_accept_fq_100_1'), lessThan(_top(tester, 'freight_accept_fq_100_2')));

      await _tap(tester, 'freight_sort_score');
      expect(_top(tester, 'freight_accept_fq_100_1'), lessThan(_top(tester, 'freight_accept_fq_100_3')));

      // explanation is rendered from the numbers, localized
      await _tap(tester, 'freight_why_fq_100_1');
      expect(find.textContaining('Price: 92% of the best price'), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('accept asks for confirmation, then awards', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await _pump(tester, '/logistics/freight/requests/fr_100', repo);
      await _tap(tester, 'freight_accept_fq_100_2');
      expect(find.text('Accept this quote?'), findsOneWidget);
      // cancel keeps the request open
      await _tap(tester, 'freight_accept_dialog_cancel');
      expect((await repo.getRequest('fr_100')).status, 'open');
      await _tap(tester, 'freight_accept_fq_100_2');
      await _tap(tester, 'freight_accept_dialog_confirm');
      final r = await repo.getRequest('fr_100');
      expect(r.status, 'awarded');
      expect(r.awardedQuoteId, 'fq_100_2');
      expect(find.byKey(k('freight_awarded_banner')), findsOneWidget);
      expect(find.byKey(k('freight_accept_fq_100_1')), findsNothing);
      expect(find.byKey(k('freight_complete_request')), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('already_awarded is shown as a localized error', (tester) async {
      final repo = _AcceptFails();
      await _pump(tester, '/logistics/freight/requests/fr_100', repo);
      await _tap(tester, 'freight_accept_fq_100_1');
      await _tap(tester, 'freight_accept_dialog_confirm');
      expect(find.byKey(k('freight_action_error')), findsOneWidget);
      expect(find.text('This request was already awarded to another quote.'), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('cancel an open request after confirmation', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await _pump(tester, '/logistics/freight/requests/fr_100', repo);
      await _tap(tester, 'freight_cancel_request');
      await _tap(tester, 'freight_close_dialog_confirm');
      final r = await repo.getRequest('fr_100');
      expect(r.status, 'closed');
      expect(r.outcome, 'cancelled');
      expect(find.byKey(k('freight_cancel_request')), findsNothing);
      expect(find.byKey(k('freight_rate_card')), findsNothing);
      await _dispose(tester);
    });

    testWidgets('rate the forwarder after completion, once', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await _pump(tester, '/logistics/freight/requests/fr_101', repo);
      expect(find.byKey(k('freight_rate_card')), findsOneWidget);
      // no stars chosen yet
      await _tap(tester, 'freight_rate_submit');
      expect(find.text('Choose a star rating.'), findsOneWidget);
      await _tap(tester, 'freight_star_5');
      await tester.enterText(find.byKey(k('freight_rate_comment')), 'Fast and tidy');
      await _tap(tester, 'freight_rate_submit');
      expect(find.byKey(k('freight_rate_done')), findsOneWidget);
      await expectLater(
        repo.rateForwarder('fr_101', 4),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'already_rated')),
      );
      await _dispose(tester);
    });

    testWidgets('awarded request can be completed, which unlocks rating', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await _pump(tester, '/logistics/freight/requests/fr_102', repo);
      expect(find.byKey(k('freight_rate_card')), findsNothing);
      await _tap(tester, 'freight_complete_request');
      await _tap(tester, 'freight_close_dialog_confirm');
      expect((await repo.getRequest('fr_102')).outcome, 'completed');
      expect(find.byKey(k('freight_rate_card')), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('detail at 360dp and 2.0 text scale does not overflow', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await _pump(
        tester,
        '/logistics/freight/requests/fr_100',
        repo,
        locale: const Locale('ar'),
        size: const Size(360, 800),
        textScale: 2.0,
      );
      for (var i = 0; i < 10; i++) {
        await tester.drag(find.byType(ListView).first, const Offset(0, -600));
        await settle(tester, frames: 2);
      }
      expect(tester.takeException(), isNull);
      await _dispose(tester);
    });

    testWidgets('not found shows a mapped error with retry', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await _pump(tester, '/logistics/freight/requests/nope', repo);
      expect(find.byKey(k('freight_detail_error')), findsOneWidget);
      expect(find.text('Not found or no longer available.'), findsOneWidget);
      await _dispose(tester);
    });
  });

  group('report sheet', () {
    Future<void> openSheet(
      WidgetTester tester,
      Future<void> Function(String, String?) submit,
    ) async {
      tester.view.physicalSize = const Size(800, 2400);
      tester.view.devicePixelRatio = 2.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('en'),
          supportedLocales: const [Locale('ar'), Locale('en')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          home: Builder(
            builder: (context) => Scaffold(
              body: Center(
                child: ElevatedButton(
                  key: k('open_sheet'),
                  onPressed: () => showFreightReportSheet(context, title: 'Report quote', submit: submit),
                  child: const Text('open'),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.byKey(k('open_sheet')));
      await settle(tester, frames: 4);
    }

    testWidgets('needs a reason, sends reason and details, then closes', (tester) async {
      final sent = <String>[];
      await openSheet(tester, (reason, details) async => sent.add('$reason|$details'));
      await _tap(tester, 'freight_report_submit');
      expect(find.text('Pick a reason.'), findsOneWidget);
      expect(sent, isEmpty);
      await _tap(tester, 'freight_reason_scam_or_fraud');
      await tester.enterText(find.byKey(k('freight_report_details')), 'asked for deposit');
      await _tap(tester, 'freight_report_submit');
      expect(sent, ['scam_or_fraud|asked for deposit']);
      expect(find.byKey(k('freight_report_submit')), findsNothing);
      await _dispose(tester);
    });

    testWidgets('429 keeps the sheet open with the Retry-After message', (tester) async {
      await openSheet(
        tester,
        (reason, details) async => throw ApiException(
          status: 429,
          code: 'rate_limited',
          message: 'x',
          retryAfterSeconds: 600,
        ),
      );
      await _tap(tester, 'freight_reason_spam');
      await _tap(tester, 'freight_report_submit');
      expect(find.text('Too many attempts. Try again in about 10 minutes.'), findsOneWidget);
      expect(find.byKey(k('freight_report_submit')), findsOneWidget);
      await _dispose(tester);
    });
  });

  group('forwarder', () {
    testWidgets('non-forwarder sees the application call to action', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await _pump(tester, '/logistics/freight', repo);
      await _tap(tester, 'freight_tab_forwarder');
      expect(find.byKey(k('freight_apply')), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('apply screen sends lanes, modes, incoterms and certifications', (tester) async {
      final repo = MockFreightRepository(clock: _clock, autoApprove: false);
      await _pump(tester, '/logistics/freight/forwarder/apply', repo);
      // too short
      await _tap(tester, 'freight_apply_submit');
      expect(find.text('Company name must be 2 to 120 characters.'), findsOneWidget);
      await tester.enterText(find.byKey(k('freight_company')), 'Silk Route Logistics');
      await tester.enterText(find.byKey(k('freight_certs')), 'FIATA, ISO 9001');
      await _tap(tester, 'freight_lane_add');
      await _tap(tester, 'freight_apply_mode_air');
      await _tap(tester, 'freight_apply_incoterm_EXW');
      await _tap(tester, 'freight_apply_submit');

      final apps = (await repo.myApplications()).items;
      expect(apps, hasLength(1));
      final a = apps.single;
      expect(a.status, 'pending');
      expect(a.companyName, 'Silk Route Logistics');
      expect(a.lanes, [
        const Lane(origin: 'CN', destination: 'IQ'),
        const Lane(origin: '*', destination: '*'),
      ]);
      expect(a.modes, ['sea', 'air']);
      expect(a.incoterms, ['EXW', 'FOB']);
      expect(a.certifications, ['FIATA', 'ISO 9001']);
      // back on the freight home; the forwarder tab shows the pending state
      await _tap(tester, 'freight_tab_forwarder');
      expect(find.text('Pending review'), findsOneWidget);
      expect(find.byKey(k('freight_apply')), findsNothing);
      await _dispose(tester);
    });

    testWidgets('apply screen maps content_rejected', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await _pump(tester, '/logistics/freight/forwarder/apply', repo);
      await tester.enterText(find.byKey(k('freight_company')), 'Call me@x.com');
      await _tap(tester, 'freight_apply_submit');
      expect(find.byKey(k('freight_apply_error')), findsOneWidget);
      expect(find.textContaining('prohibited goods. Edit it'), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('inbox lists matching requests and opens the quote form', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await repo.apply(_application);
      await _pump(tester, '/logistics/freight', repo);
      await _tap(tester, 'freight_tab_forwarder');
      expect(find.byKey(k('freight_inbox_fr_200')), findsOneWidget);
      expect(find.byKey(k('freight_inbox_fr_201')), findsNothing);
      await _tap(tester, 'freight_inbox_fr_200');
      expect(find.byKey(k('freight_quote_submit')), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('submit validates breakdown sum, then sends; revise and withdraw', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await repo.apply(_application);
      await _pump(tester, '/logistics/freight/forwarder/requests/fr_200', repo);

      // currency is fixed, not editable
      final currency = tester.widget<TextFormField>(find.byKey(k('freight_quote_currency')));
      expect(currency.enabled, isFalse);

      await tester.enterText(find.byKey(k('freight_quote_amount')), '100.00');
      await tester.enterText(find.byKey(k('freight_quote_transit')), '30');
      await _tap(tester, 'freight_line_add');
      await _tap(tester, 'freight_line_add');
      await tester.enterText(find.byKey(k('freight_line_label_0')), 'Ocean');
      await tester.enterText(find.byKey(k('freight_line_amount_0')), '60.00');
      await tester.enterText(find.byKey(k('freight_line_label_1')), 'Local');
      await tester.enterText(find.byKey(k('freight_line_amount_1')), '30.10');
      await settle(tester, frames: 2);
      expect(find.textContaining('does not match the total'), findsOneWidget);

      await _tap(tester, 'freight_quote_submit');
      expect(find.text('The breakdown lines must add up to the total exactly.'), findsOneWidget);
      expect((await repo.myQuotes()).items, isEmpty);

      await tester.enterText(find.byKey(k('freight_line_amount_1')), '40.00');
      await settle(tester, frames: 2);
      expect(find.textContaining('matches the total'), findsOneWidget);
      await _tap(tester, 'freight_quote_submit');
      final quotes = (await repo.myQuotes()).items;
      expect(quotes, hasLength(1));
      expect(quotes.single.amount, '100.00');
      expect(quotes.single.currency, 'USD');
      expect(quotes.single.breakdown.map((l) => l.amount), ['60.00', '40.00']);
      expect(find.byKey(k('freight_existing_quote')), findsOneWidget);
      expect(find.byKey(k('freight_quote_withdraw')), findsOneWidget);

      // revise (same quote id, revision 2)
      // the form was reloaded from the saved quote: its lines got new ids (2, 3)
      await tester.enterText(find.byKey(k('freight_quote_amount')), '110.00');
      await tester.enterText(find.byKey(k('freight_line_amount_3')), '50.00');
      await _tap(tester, 'freight_quote_submit');
      final revised = (await repo.myQuotes()).items.single;
      expect(revised.id, quotes.single.id);
      expect(revised.revision, 2);
      expect(revised.amount, '110.00');

      // withdraw with confirmation
      await _tap(tester, 'freight_quote_withdraw');
      await _tap(tester, 'freight_withdraw_confirm');
      expect((await repo.myQuotes()).items.single.status, 'withdrawn');
      expect(find.text('Resubmit quote'), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('quote form shows the existing quote of the forwarder', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await repo.apply(_application);
      await repo.submitQuote('fr_200', _tinyQuote);
      await _pump(tester, '/logistics/freight/forwarder/requests/fr_200', repo);
      expect(find.byKey(k('freight_existing_quote')), findsOneWidget);
      await _dispose(tester);
    });

    testWidgets('forwarder views at 360dp and 2.0 text scale do not overflow', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await repo.apply(_application);
      await _pump(
        tester,
        '/logistics/freight/forwarder/requests/fr_200',
        repo,
        locale: const Locale('ar'),
        size: const Size(360, 800),
        textScale: 2.0,
      );
      for (var i = 0; i < 8; i++) {
        await tester.drag(find.byType(ListView).first, const Offset(0, -500));
        await settle(tester, frames: 2);
      }
      expect(tester.takeException(), isNull);
      await _dispose(tester);
    });

    testWidgets('apply form at 360dp and 2.0 text scale does not overflow', (tester) async {
      final repo = MockFreightRepository(clock: _clock);
      await _pump(
        tester,
        '/logistics/freight/forwarder/apply',
        repo,
        locale: const Locale('ar'),
        size: const Size(360, 800),
        textScale: 2.0,
      );
      for (var i = 0; i < 10; i++) {
        await tester.drag(find.byType(ListView).first, const Offset(0, -500));
        await settle(tester, frames: 2);
      }
      expect(tester.takeException(), isNull);
      await _dispose(tester);
    });
  });
}
