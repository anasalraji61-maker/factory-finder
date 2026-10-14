import 'dart:typed_data';

import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/discover/data/listing_report.dart';
import 'package:factory_finder/features/my_products/media/image_pick_service.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';
import 'package:factory_finder/features/my_products/my_products_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'test_app.dart';

class _FixedAuth extends AuthController {
  _FixedAuth(Ref ref, Me me) : super(ref) {
    state = me;
  }
}

const Me _verified = Me(
  id: 'usr_s',
  name: 'Supplier',
  supplierId: 'sup_iq_001',
  supplierClaimStatus: 'verified',
);

/// Report repository whose outcome the test controls.
class _ScriptedDiscover extends DiscoverRepository {
  _ScriptedDiscover(super.api);

  Object? error;
  final List<(String, ListingReportReason, String?)> calls = [];

  @override
  Future<void> reportListing(
    String id,
    ListingReportReason reason, {
    String? details,
  }) async {
    calls.add((id, reason, details));
    final e = error;
    if (e != null) throw e;
  }
}

Future<GoRouter> _pump(
  WidgetTester tester, {
  List<Override> overrides = const <Override>[],
  double height = 2400,
}) async {
  tester.view.physicalSize = Size(1080, height);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final router = createAppRouter();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        secureStoreProvider.overrideWithValue(MemoryStore()),
        ...overrides,
      ],
      child: FactoryFinderApp(router: router),
    ),
  );
  await settle(tester);
  return router;
}

Finder _keyStartsWith(String prefix) => find.byWidgetPredicate((w) {
      final k = w.key;
      return k is ValueKey<String> && k.value.startsWith(prefix);
    });

PickedImage _png() => PickedImage(
      bytes: Uint8List.fromList(<int>[1, 2, 3]),
      filename: 'a.png',
      mime: 'image/png',
    );

/// Lets snackbars (which cover the composer) expire.
Future<void> _expireSnack(WidgetTester tester) async {
  await tester.pump(const Duration(seconds: 5));
  await settle(tester, frames: 4);
}

Future<void> _attachOne(WidgetTester tester) async {
  await tester.tap(find.byKey(const ValueKey('chat-attach')));
  await settle(tester, frames: 4);
  await tester.tap(find.byKey(const ValueKey('chat-attach-gallery')));
  await settle(tester, frames: 8);
}

void main() {
  setUpWidgetTests();

  group('chat attachments', () {
    testWidgets('attach, remove, send, then bubble and list preview', (tester) async {
      final picker = FakeImagePickService(next: _png());
      final router = await _pump(
        tester,
        overrides: [imagePickServiceProvider.overrideWithValue(picker)],
      );
      router.go('/chat/cnv_002');
      await settle(tester, frames: 6);

      await _attachOne(tester);
      await _attachOne(tester);
      expect(picker.galleryCalls, 2);
      expect(find.byKey(const ValueKey('chat-attach-thumb-0')), findsOneWidget);
      expect(find.byKey(const ValueKey('chat-attach-thumb-1')), findsOneWidget);

      await tester.tap(find.byKey(const ValueKey('chat-attach-remove-0')));
      await settle(tester, frames: 2);
      expect(find.byKey(const ValueKey('chat-attach-thumb-1')), findsNothing);
      expect(find.byKey(const ValueKey('chat-attach-thumb-0')), findsOneWidget);

      // Attachment-only message: no text needed.
      await tester.tap(find.byKey(const ValueKey('chat-send')));
      await settle(tester, frames: 6);
      expect(find.byKey(const ValueKey('chat-attach-strip')), findsNothing);
      expect(_keyStartsWith('chat-img-'), findsOneWidget);

      // Conversation list shows a localised preview and a thumbnail.
      router.go('/messages');
      await settle(tester, frames: 6);
      expect(find.text('📷 صورة'), findsOneWidget);
      expect(find.byKey(const ValueKey('conv-thumb-cnv_002')), findsOneWidget);
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });

    testWidgets('limit of five images, cancel and oversize are handled', (tester) async {
      final picker = FakeImagePickService(next: _png());
      final router = await _pump(
        tester,
        overrides: [imagePickServiceProvider.overrideWithValue(picker)],
      );
      router.go('/chat/cnv_001');
      await settle(tester, frames: 6);

      for (var i = 0; i < 5; i++) {
        await _attachOne(tester);
      }
      expect(find.byKey(const ValueKey('chat-attach-thumb-4')), findsOneWidget);

      await tester.tap(find.byKey(const ValueKey('chat-attach')));
      await settle(tester, frames: 4);
      expect(find.text('الحد الأقصى 5 صور في الرسالة الواحدة.'), findsOneWidget);
      expect(picker.galleryCalls, 5);
      await _expireSnack(tester);

      // Remove one, then an oversized file is rejected without a thumbnail.
      await tester.tap(find.byKey(const ValueKey('chat-attach-remove-4')));
      await settle(tester, frames: 2);
      picker.next = PickedImage(
        bytes: Uint8List(5 * 1024 * 1024 + 1),
        filename: 'big.jpg',
        mime: 'image/jpeg',
      );
      await _attachOne(tester);
      expect(find.text('الصورة أكبر من 5 ميغابايت.'), findsOneWidget);
      expect(find.byKey(const ValueKey('chat-attach-thumb-4')), findsNothing);

      // User cancels the picker: nothing changes.
      picker.next = null;
      await _expireSnack(tester);
      await _attachOne(tester);
      expect(find.byKey(const ValueKey('chat-attach-thumb-3')), findsOneWidget);
      expect(find.byKey(const ValueKey('chat-attach-thumb-4')), findsNothing);
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });

    testWidgets('fixture thread renders an image bubble', (tester) async {
      final router = await _pump(tester);
      router.go('/chat/cnv_004');
      await settle(tester, frames: 6);
      expect(find.byKey(const ValueKey('chat-img-cnv_004_att-0')), findsOneWidget);
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });
  });

  group('listing report', () {
    Future<_ScriptedDiscover> openSheet(WidgetTester tester) async {
      final repo = _ScriptedDiscover(ApiClient(baseUrl: 'http://x', isMock: true));
      final router = await _pump(
        tester,
        overrides: [discoverRepositoryProvider.overrideWithValue(repo)],
      );
      router.go('/listing/lst_001');
      await settle(tester, frames: 6);
      await tester.tap(find.byKey(const ValueKey('listing-report')));
      await settle(tester, frames: 5);
      expect(find.byKey(const ValueKey('report-sheet')), findsOneWidget);
      return repo;
    }

    testWidgets('reason is required, then the report is sent and acknowledged', (tester) async {
      final repo = await openSheet(tester);
      await tester.tap(find.byKey(const ValueKey('report-submit')));
      await settle(tester, frames: 2);
      expect(find.text('اختر سبب البلاغ'), findsOneWidget);
      expect(repo.calls, isEmpty);

      await tester.tap(find.byKey(const ValueKey('report-reason-scam_or_fraud')));
      await settle(tester, frames: 2);
      await tester.enterText(find.byKey(const ValueKey('report-details')), 'asks for advance');
      await tester.tap(find.byKey(const ValueKey('report-submit')));
      await settle(tester, frames: 8);

      expect(repo.calls.single.$1, 'lst_001');
      expect(repo.calls.single.$2, ListingReportReason.scamOrFraud);
      expect(repo.calls.single.$3, 'asks for advance');
      expect(find.byKey(const ValueKey('report-sheet')), findsNothing);
      expect(find.text('تم استلام بلاغك. شكراً لمساعدتك.'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });

    testWidgets('own listing (409) and rate limit (429) keep the sheet open', (tester) async {
      final repo = await openSheet(tester);
      await tester.tap(find.byKey(const ValueKey('report-reason-offensive')));
      await settle(tester, frames: 2);

      repo.error = ApiException(status: 409, code: 'own_listing', message: 'own');
      await tester.tap(find.byKey(const ValueKey('report-submit')));
      await settle(tester, frames: 4);
      expect(find.text('لا يمكنك الإبلاغ عن منتجك.'), findsOneWidget);
      expect(find.byKey(const ValueKey('report-sheet')), findsOneWidget);

      repo.error = ApiException(
        status: 429,
        code: 'rate_limited',
        message: 'slow down',
        retryAfterSeconds: 1800,
      );
      await tester.tap(find.byKey(const ValueKey('report-submit')));
      await settle(tester, frames: 4);
      expect(find.text('أرسلت بلاغات كثيرة. حاول بعد 30 دقيقة.'), findsOneWidget);
      expect(find.byKey(const ValueKey('report-sheet')), findsOneWidget);
      expect(repo.calls, hasLength(2));

      repo.error = ApiException(status: 401, code: 'unauthorized', message: 'no');
      await tester.tap(find.byKey(const ValueKey('report-submit')));
      await settle(tester, frames: 4);
      expect(find.text('سجّل الدخول للإبلاغ عن منتج.'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });
  });

  group('my products moderation', () {
    OwnedListing listing(String id, ListingStatus status,
            {String? reason, String? source}) =>
        OwnedListing(
          id: id,
          status: status,
          kind: ListingKind.product,
          condition: ItemCondition.brandNew,
          title: 'Item $id',
          category: 'lighting',
          moq: 10,
          price: const MoneyRange(
            min: Money(amount: '2.50', currency: 'USD'),
            max: Money(amount: '4.00', currency: 'USD'),
          ),
          moderationReason: reason,
          moderationSource: source,
        );

    testWidgets('banner and hidden publish on cards and in the editor', (tester) async {
      final router = await _pump(
        tester,
        height: 9000,
        overrides: [
          authProvider.overrideWith((ref) => _FixedAuth(ref, _verified)),
          myListingsRepositoryProvider.overrideWithValue(
            MyListingsRepository(
              ApiClient(baseUrl: 'http://unused.invalid', isMock: true),
              MockMyListingsBackend(seed: [
                listing('lst_pr', ListingStatus.pendingReview,
                    reason: 'Received 3 reports', source: 'report'),
                listing('lst_hd', ListingStatus.hidden, reason: 'Prohibited item', source: 'admin'),
                listing('lst_ok', ListingStatus.published),
              ]),
            ),
          ),
        ],
      );
      router.go('/my-products');
      await settle(tester, frames: 10);

      expect(find.byKey(const ValueKey('myp-mod-lst_pr')), findsOneWidget);
      expect(find.text('السبب: Received 3 reports'), findsOneWidget);
      expect(find.byKey(const ValueKey('myp-mod-lst_hd')), findsOneWidget);
      expect(find.text('السبب: Prohibited item'), findsOneWidget);
      expect(find.byKey(const ValueKey('myp-mod-lst_ok')), findsNothing);

      // Moderated cards cannot be published; the published one can be unpublished.
      expect(find.byKey(const ValueKey('myp-publish-lst_pr')), findsNothing);
      expect(find.byKey(const ValueKey('myp-publish-lst_hd')), findsNothing);
      expect(find.byKey(const ValueKey('myp-unpublish-lst_ok')), findsOneWidget);
      expect(find.byKey(const ValueKey('myp-edit-lst_pr')), findsOneWidget);
      expect(find.byKey(const ValueKey('myp-delete-lst_pr')), findsOneWidget);

      // Filter chip for the moderation state.
      await tester.ensureVisible(find.byKey(const ValueKey('myp-filter-hidden')));
      await tester.pump(const Duration(milliseconds: 300));
      await tester.tap(find.byKey(const ValueKey('myp-filter-hidden')));
      await settle(tester, frames: 8);
      expect(find.byKey(const ValueKey('myp-card-lst_hd')), findsOneWidget);
      expect(find.byKey(const ValueKey('myp-card-lst_pr')), findsNothing);

      // Editor repeats the notice and offers no publish button.
      await tester.tap(find.byKey(const ValueKey('myp-edit-lst_hd')));
      await settle(tester, frames: 10);
      expect(find.byKey(const ValueKey('myp-editor')), findsOneWidget);
      expect(find.byKey(const ValueKey('myp-mod-lst_hd')), findsOneWidget);
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('myp-editor-delete')),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.byKey(const ValueKey('myp-editor-publish')), findsNothing);
      expect(find.byKey(const ValueKey('myp-editor-unpublish')), findsNothing);
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });
  });
}
