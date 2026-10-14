import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';
import 'package:factory_finder/features/my_products/my_products_repository.dart';
import 'package:factory_finder/features/my_products/screens/my_products_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

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

OwnedListing _listing(String id, String title, ListingStatus status) => OwnedListing(
      id: id,
      status: status,
      kind: ListingKind.product,
      condition: ItemCondition.brandNew,
      title: title,
      category: 'lighting',
      moq: 10,
      price: const MoneyRange(
        min: Money(amount: '2.50', currency: 'USD'),
        max: Money(amount: '4.00', currency: 'USD'),
      ),
    );

Future<void> _pump(
  WidgetTester tester, {
  required Me me,
  List<OwnedListing> seed = const <OwnedListing>[],
  bool live = false,
}) async {
  tester.view.physicalSize = const Size(1080, 9000);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final router = createAppRouter();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        secureStoreProvider.overrideWithValue(MemoryStore()),
        authProvider.overrideWith((ref) => _FixedAuth(ref, me)),
        if (live) myProductsBypassGateProvider.overrideWithValue(false),
        myListingsRepositoryProvider.overrideWithValue(
          MyListingsRepository(
            ApiClient(baseUrl: 'http://unused.invalid', isMock: true),
            MockMyListingsBackend(seed: seed),
          ),
        ),
      ],
      child: FactoryFinderApp(router: router),
    ),
  );
  await settle(tester);
  router.go('/my-products');
  await settle(tester, frames: 10);
}

void main() {
  setUpWidgetTests();

  testWidgets('my products: validation, then create a draft from the editor', (tester) async {
    await _pump(tester, me: _verified);
    expect(find.text('لا توجد منتجات بعد'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('myp-add')));
    await settle(tester);
    expect(find.byKey(const ValueKey('myp-editor')), findsOneWidget);

    // Empty form: errors appear and nothing is saved.
    await tester.tap(find.byKey(const ValueKey('myp-save')));
    await settle(tester, frames: 3);
    expect(find.text('العنوان مطلوب'), findsOneWidget);
    expect(find.text('اختر فئة'), findsOneWidget);
    expect(find.byKey(const ValueKey('myp-editor')), findsOneWidget);

    await tester.enterText(find.byKey(const ValueKey('myp-title')), 'Test lamp');
    await tester.tap(find.byKey(const ValueKey('myp-cat-lighting')));
    await tester.enterText(find.byKey(const ValueKey('myp-price-min')), '2.5');
    await tester.enterText(find.byKey(const ValueKey('myp-price-max')), '4');
    await settle(tester, frames: 2);

    // An invalid image URL is rejected, a valid one is added.
    await tester.enterText(find.byKey(const ValueKey('myp-image-input')), 'not a url');
    await tester.tap(find.byKey(const ValueKey('myp-image-add')));
    await settle(tester, frames: 2);
    expect(find.text('رابط صورة غير صالح (يجب أن يبدأ بـ http أو https)'), findsOneWidget);
    await tester.enterText(
        find.byKey(const ValueKey('myp-image-input')), 'https://example.com/a.jpg');
    await tester.tap(find.byKey(const ValueKey('myp-image-add')));
    await settle(tester, frames: 2);
    expect(find.text('https://example.com/a.jpg'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('myp-save')));
    await settle(tester, frames: 12);

    expect(find.byKey(const ValueKey('myp-editor')), findsNothing);
    expect(find.text('Test lamp'), findsOneWidget);
    expect(find.text('مسودة'), findsWidgets);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('my products: filter chips, publish and delete with confirm dialogs', (tester) async {
    await _pump(tester, me: _verified, seed: [
      _listing('lst_a', 'Draft A', ListingStatus.draft),
      _listing('lst_b', 'Pub B', ListingStatus.published),
    ]);
    expect(find.text('Draft A'), findsOneWidget);
    expect(find.text('Pub B'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('myp-filter-draft')));
    await settle(tester);
    expect(find.text('Draft A'), findsOneWidget);
    expect(find.text('Pub B'), findsNothing);

    // Cancel keeps the draft unpublished; confirm publishes it.
    await tester.tap(find.byKey(const ValueKey('myp-publish-lst_a')));
    await settle(tester, frames: 3);
    await tester.tap(find.byKey(const ValueKey('myp-confirm-cancel')));
    await settle(tester, frames: 3);
    expect(find.text('Draft A'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('myp-publish-lst_a')));
    await settle(tester, frames: 3);
    await tester.tap(find.byKey(const ValueKey('myp-confirm-ok')));
    await settle(tester, frames: 12);
    expect(find.text('تم نشر المنتج'), findsOneWidget);
    expect(find.text('Draft A'), findsNothing);
    expect(find.text('لا توجد منتجات في هذا التصنيف'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('myp-filter-all')));
    await settle(tester);
    expect(find.text('Draft A'), findsOneWidget);
    expect(find.byKey(const ValueKey('myp-unpublish-lst_a')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('myp-delete-lst_b')));
    await settle(tester, frames: 3);
    await tester.tap(find.byKey(const ValueKey('myp-confirm-ok')));
    await settle(tester, frames: 12);
    expect(find.text('Pub B'), findsNothing);
    expect(find.text('Draft A'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('my products: unverified supplier sees the claim card', (tester) async {
    await _pump(
      tester,
      live: true,
      me: const Me(
        id: 'usr_p',
        name: 'Pending',
        supplierId: 'sup_iq_002',
        supplierClaimStatus: 'pending',
      ),
    );
    expect(find.byKey(const ValueKey('myp-claim-card')), findsOneWidget);
    expect(find.byKey(const ValueKey('myp-add')), findsNothing);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
