import 'dart:typed_data';

import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/my_products/media/image_pick_service.dart';
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

void main() {
  setUpWidgetTests();

  testWidgets('product editor: upload from gallery, size check, reorder, remove',
      (tester) async {
    tester.view.physicalSize = const Size(1080, 9000);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final picker = FakeImagePickService();
    final router = createAppRouter();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          keyValueStoreProvider.overrideWithValue(MemoryStore()),
          secureStoreProvider.overrideWithValue(MemoryStore()),
          authProvider.overrideWith((ref) => _FixedAuth(ref, _verified)),
          imagePickServiceProvider.overrideWithValue(picker),
          myListingsRepositoryProvider.overrideWithValue(
            MyListingsRepository(
              ApiClient(baseUrl: 'http://unused.invalid', isMock: true),
              MockMyListingsBackend(),
            ),
          ),
        ],
        child: FactoryFinderApp(router: router),
      ),
    );
    await settle(tester);
    router.go('/my-products');
    await settle(tester, frames: 10);
    await tester.tap(find.byKey(const ValueKey('myp-add')));
    await settle(tester);
    expect(find.byKey(const ValueKey('myp-editor')), findsOneWidget);

    // Oversized file: rejected client-side with a clear snackbar.
    picker.next = PickedImage(
      bytes: Uint8List(5 * 1024 * 1024 + 1),
      filename: 'big.jpg',
      mime: 'image/jpeg',
    );
    await tester.tap(find.byKey(const ValueKey('myp-image-gallery')));
    await settle(tester, frames: 3);
    expect(find.text('الصورة أكبر من 5 ميغابايت.'), findsOneWidget);
    expect(find.byKey(const ValueKey('myp-image-tile-0')), findsNothing);

    // Valid files upload (mock repo) and become tiles.
    picker.next = PickedImage(
      bytes: Uint8List.fromList(<int>[1, 2, 3]),
      filename: 'a.png',
      mime: 'image/png',
    );
    await tester.tap(find.byKey(const ValueKey('myp-image-gallery')));
    await settle(tester, frames: 8);
    await tester.tap(find.byKey(const ValueKey('myp-image-camera')));
    await settle(tester, frames: 8);
    expect(picker.galleryCalls, 2);
    expect(picker.cameraCalls, 1);
    expect(find.byKey(const ValueKey('myp-image-tile-0')), findsOneWidget);
    expect(find.byKey(const ValueKey('myp-image-tile-1')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('myp-image-later-0')));
    await settle(tester, frames: 2);
    await tester.tap(find.byKey(const ValueKey('myp-image-remove-1')));
    await settle(tester, frames: 2);
    expect(find.byKey(const ValueKey('myp-image-tile-1')), findsNothing);
    expect(find.byKey(const ValueKey('myp-image-tile-0')), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('notification prefs: pending digest email, wrong then right code',
      (tester) async {
    await pumpApp(tester, location: '/notification-prefs');
    tester.view.physicalSize = const Size(1080, 9000);
    await settle(tester, frames: 3);

    await tester.enterText(find.byKey(const Key('np_email')), 'user@example.com');
    await tester.tap(find.text('حفظ التغييرات'));
    await settle(tester, frames: 6);
    expect(find.byKey(const Key('np_pending')), findsOneWidget);
    expect(find.textContaining('u***@e***.com'), findsOneWidget);
    // Resend is on its 60s cooldown right after the code was mailed.
    expect(find.textContaining('إعادة الإرسال بعد'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('np_code')), '000000');
    await tester.tap(find.byKey(const Key('np_verify')));
    await settle(tester, frames: 6);
    expect(find.text('الرمز غير صحيح'), findsWidgets);
    expect(find.byKey(const Key('np_verified_badge')), findsNothing);

    await tester.enterText(find.byKey(const Key('np_code')), '123456');
    await tester.tap(find.byKey(const Key('np_verify')));
    await settle(tester, frames: 6);
    expect(find.byKey(const Key('np_verified_badge')), findsOneWidget);
    expect(find.byKey(const Key('np_pending')), findsNothing);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
