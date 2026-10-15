import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

Future<void> _pump(WidgetTester tester, {required bool banner}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        secureStoreProvider.overrideWithValue(MemoryStore()),
      ],
      child: FactoryFinderApp(router: createAppRouter(), showMockBanner: banner),
    ),
  );
  await settle(tester);
}

void main() {
  setUpWidgetTests();

  test('server url override rules', () {
    // dev / debug: always allowed
    expect(serverUrlOverrideAllowed(release: false, pinned: true, allowFlag: false), isTrue);
    // release without a build-time URL: the default is useless, so allowed
    expect(serverUrlOverrideAllowed(release: true, pinned: false, allowFlag: false), isTrue);
    // release pinned to a build-time URL: ignored...
    expect(serverUrlOverrideAllowed(release: true, pinned: true, allowFlag: false), isFalse);
    // ...unless the developer toggle is on
    expect(serverUrlOverrideAllowed(release: true, pinned: true, allowFlag: true), isTrue);
  });

  test('tests never run as a release mock build', () {
    expect(kReleaseMockBuild, isFalse);
  });

  testWidgets('mock banner is shown only when requested', (tester) async {
    await _pump(tester, banner: true);
    expect(find.byKey(const ValueKey<String>('mock-release-banner')), findsOneWidget);
    await disposeApp(tester);
    await _pump(tester, banner: false);
    expect(find.byKey(const ValueKey<String>('mock-release-banner')), findsNothing);
    await disposeApp(tester);
  });
}
