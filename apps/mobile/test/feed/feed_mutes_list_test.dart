import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/feed/feed_controller.dart';
import 'package:factory_finder/features/feed/feed_models.dart';
import 'package:factory_finder/features/feed/feed_repository.dart';
import 'package:factory_finder/features/feed/screens/feed_screen.dart';
import 'package:factory_finder/features/feed/screens/muted_suppliers_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../widgets/test_app.dart';

class _Rec implements HttpClientAdapter {
  final List<RequestOptions> calls = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return ResponseBody.fromString(
      jsonEncode(<String, Object?>{
        'items': <Object?>[
          <String, Object?>{'supplier_id': 'sup_cn_003', 'muted_at': '2026-10-01T10:00:00Z'},
        ],
        'next_cursor': 'c2',
      }),
      200,
      headers: <String, List<String>>{
        Headers.contentTypeHeader: <String>[Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

/// Always reports another page, to prove the page cap.
class _Endless extends MockFeedRepository {
  int pages = 0;

  @override
  Future<FeedPage<MutedSupplier>> listMutes({String? cursor, int limit = 50}) async {
    pages++;
    return FeedPage<MutedSupplier>(
      items: <MutedSupplier>[MutedSupplier(supplierId: 'sup_$pages')],
      nextCursor: 'next',
    );
  }
}

class _FixedAuth extends AuthController {
  _FixedAuth(Ref ref, Me? me) : super(ref) {
    state = me;
  }
}

const Me _buyer = Me(id: 'usr_buyer', name: 'Buyer');

List<Override> _overrides(FeedRepository repo, {Me? me}) => <Override>[
      keyValueStoreProvider.overrideWithValue(MemoryStore()),
      secureStoreProvider.overrideWithValue(MemoryStore()),
      feedRepositoryProvider.overrideWithValue(repo),
      if (me != null) authProvider.overrideWith((ref) => _FixedAuth(ref, me)),
    ];

Future<void> _pumpHome(WidgetTester tester, Widget home, List<Override> overrides) async {
  tester.view.physicalSize = const Size(360, 800);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final router = GoRouter(routes: <RouteBase>[
    GoRoute(path: '/', builder: (c, s) => home),
    GoRoute(path: '/feed/muted', builder: (c, s) => const MutedSuppliersScreen()),
  ]);
  await tester.pumpWidget(
    ProviderScope(
      overrides: overrides,
      child: MaterialApp.router(
        routerConfig: router,
        locale: const Locale('en'),
        supportedLocales: const <Locale>[Locale('ar'), Locale('en')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
      ),
    ),
  );
  await settle(tester);
}

void main() {
  setUpWidgetTests();

  test('live listMutes sends GET /v1/feed/mutes with cursor and limit', () async {
    final rec = _Rec();
    final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = rec;
    final repo = LiveFeedRepository(ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio));
    final page = await repo.listMutes(cursor: 'c1', limit: 20);
    expect(rec.calls.last.method, 'GET');
    expect(rec.calls.last.path, '/v1/feed/mutes');
    expect(rec.calls.last.queryParameters, <String, dynamic>{'limit': 20, 'cursor': 'c1'});
    expect(page.items.single.supplierId, 'sup_cn_003');
    expect(page.items.single.mutedAt, isNotNull);
    expect(page.nextCursor, 'c2');
  });

  test('mock listMutes pages most recent first', () async {
    final repo = MockFeedRepository();
    await repo.muteSupplier('sup_cn_001');
    await repo.muteSupplier('sup_cn_002');
    await repo.muteSupplier('sup_cn_003');
    final p1 = await repo.listMutes(limit: 2);
    expect(p1.items.map((m) => m.supplierId), <String>['sup_cn_003', 'sup_cn_002']);
    final p2 = await repo.listMutes(cursor: p1.nextCursor, limit: 2);
    expect(p2.items.map((m) => m.supplierId), <String>['sup_cn_001']);
    expect(p2.nextCursor, isNull);
    await repo.unmuteSupplier('sup_cn_003');
    expect((await repo.listMutes()).items.length, 2);
  });

  test('fetchAllMutes follows cursors up to 10 pages', () async {
    final repo = _Endless();
    final ids = await fetchAllMutes(repo);
    expect(repo.pages, kMaxMutePages);
    expect(ids.length, kMaxMutePages);
  });

  test('mutedSuppliersProvider loads the server set once after sign-in', () async {
    final repo = MockFeedRepository();
    await repo.muteSupplier('sup_cn_002');
    final c = ProviderContainer(overrides: _overrides(repo, me: _buyer));
    addTearDown(c.dispose);
    expect(c.read(mutedSuppliersProvider), isEmpty);
    await Future<void>.delayed(Duration.zero);
    await Future<void>.delayed(Duration.zero);
    expect(c.read(mutedSuppliersProvider), <String>{'sup_cn_002'});
  });

  test('mutedSuppliersProvider does not load for guests', () async {
    final repo = _Endless();
    final c = ProviderContainer(overrides: _overrides(repo));
    addTearDown(c.dispose);
    c.read(mutedSuppliersProvider);
    await Future<void>.delayed(Duration.zero);
    expect(repo.pages, 0);
    expect(c.read(mutedSuppliersProvider), isEmpty);
  });

  group('MutedSuppliersScreen', () {
    testWidgets('lists muted suppliers and unmutes one', (tester) async {
      final repo = MockFeedRepository();
      await repo.muteSupplier('sup_cn_001');
      await repo.muteSupplier('sup_cn_002');
      await _pumpHome(tester, const MutedSuppliersScreen(), _overrides(repo, me: _buyer));
      expect(find.byKey(const ValueKey<String>('muted-sup_cn_001')), findsOneWidget);
      expect(find.byKey(const ValueKey<String>('muted-sup_cn_002')), findsOneWidget);

      await tester.tap(find.byKey(const ValueKey<String>('unmute-sup_cn_001')));
      await settle(tester);
      expect(find.byKey(const ValueKey<String>('muted-sup_cn_001')), findsNothing);
      expect(find.byKey(const ValueKey<String>('muted-sup_cn_002')), findsOneWidget);
      expect((await repo.listMutes()).items.map((m) => m.supplierId), <String>['sup_cn_002']);
    });

    testWidgets('shows the empty state', (tester) async {
      await _pumpHome(tester, const MutedSuppliersScreen(), _overrides(MockFeedRepository(), me: _buyer));
      expect(find.text('No muted suppliers'), findsOneWidget);
    });

    testWidgets('feed menu opens the screen for signed-in users', (tester) async {
      await _pumpHome(tester, const FeedScreen(), _overrides(MockFeedRepository(), me: _buyer));
      await tester.tap(find.byKey(const ValueKey<String>('feed-menu')));
      await settle(tester);
      await tester.tap(find.byKey(const ValueKey<String>('feed-menu-muted')));
      await settle(tester);
      expect(find.byType(MutedSuppliersScreen), findsOneWidget);
    });

    testWidgets('guests get no menu', (tester) async {
      await _pumpHome(tester, const FeedScreen(), _overrides(MockFeedRepository()));
      expect(find.byKey(const ValueKey<String>('feed-menu')), findsNothing);
    });
  });
}
