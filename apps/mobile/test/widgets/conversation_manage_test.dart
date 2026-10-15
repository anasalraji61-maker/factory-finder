import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import 'test_app.dart';

const String _firstTitle = 'شركة شنتشن للإلكترونيات';

Future<GoRouter> _pump(WidgetTester tester, String location) async {
  tester.view.physicalSize = const Size(1080, 4800);
  tester.view.devicePixelRatio = 3.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final router = createAppRouter();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        secureStoreProvider.overrideWithValue(MemoryStore()),
      ],
      child: FactoryFinderApp(router: router),
    ),
  );
  await settle(tester);
  router.go(location);
  await settle(tester);
  return router;
}

ProviderContainer _container(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(NavigationBar)));

void main() {
  setUpWidgetTests();

  testWidgets('archive with undo, archived filter, and mute', (tester) async {
    await _pump(tester, '/messages');
    expect(find.text(_firstTitle), findsOneWidget);

    await tester.longPress(find.text(_firstTitle));
    await settle(tester, frames: 4);
    await tester.tap(find.byKey(const ValueKey<String>('conv-menu-archive')));
    await settle(tester);
    expect(find.text(_firstTitle), findsNothing);
    expect(find.text('تمت أرشفة المحادثة'), findsOneWidget);

    // Archived filter lists it.
    await tester.tap(find.byKey(const ValueKey<String>('conv-archived-toggle')));
    await settle(tester);
    expect(find.text('المحادثات المؤرشفة'), findsOneWidget);
    expect(find.text(_firstTitle), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey<String>('conv-archived-toggle')));
    await settle(tester);
    expect(find.text(_firstTitle), findsNothing);

    // Undo brings it back.
    await tester.tap(find.byKey(const ValueKey<String>('conv-undo')));
    await settle(tester);
    expect(find.text(_firstTitle), findsOneWidget);

    // Mute shows the muted icon and drops it from the badge total.
    expect(_container(tester).read(unreadTotalProvider).valueOrNull, 7);
    await tester.longPress(find.text(_firstTitle));
    await settle(tester, frames: 4);
    await tester.tap(find.byKey(const ValueKey<String>('conv-menu-mute')));
    await settle(tester);
    expect(find.byKey(const ValueKey<String>('conv-muted-cnv_001')), findsOneWidget);
    expect(_container(tester).read(unreadTotalProvider).valueOrNull, 5);
    expect(find.byKey(const ValueKey<String>('nav-messages-badge')), findsWidgets);

    await disposeApp(tester);
  });

  testWidgets('block a user from the chat menu, then unblock in settings', (tester) async {
    final router = await _pump(tester, '/messages');
    await tester.tap(find.text(_firstTitle));
    await settle(tester);

    await tester.tap(find.byKey(const ValueKey<String>('chat-menu')));
    await settle(tester, frames: 4);
    await tester.tap(find.byKey(const ValueKey<String>('chat-menu-block')));
    await settle(tester, frames: 4);
    expect(find.byKey(const ValueKey<String>('chat-block-confirm')), findsOneWidget);

    // Cancel does nothing.
    await tester.tap(find.byKey(const ValueKey<String>('chat-block-cancel')));
    await settle(tester, frames: 4);
    expect(await _container(tester).read(messagingRepositoryProvider).blockedUsers(), isEmpty);

    await tester.tap(find.byKey(const ValueKey<String>('chat-menu')));
    await settle(tester, frames: 4);
    await tester.tap(find.byKey(const ValueKey<String>('chat-menu-block')));
    await settle(tester, frames: 4);
    await tester.tap(find.byKey(const ValueKey<String>('chat-block-confirm')));
    await settle(tester);

    // Back on the list, the blocked thread is gone.
    expect(find.text(_firstTitle), findsNothing);
    final repo = _container(tester).read(messagingRepositoryProvider);
    expect((await repo.blockedUsers()).map((b) => b.userId), ['sup_001']);

    // Blocked users screen lists it and unblocks after confirmation.
    router.go('/settings/privacy/blocked');
    await settle(tester);
    expect(find.byKey(const ValueKey<String>('blocked-sup_001')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey<String>('unblock-sup_001')));
    await settle(tester, frames: 4);
    await tester.tap(find.byKey(const ValueKey<String>('blocked-confirm')));
    await settle(tester);
    expect(find.byKey(const ValueKey<String>('blocked-sup_001')), findsNothing);
    expect(await repo.blockedUsers(), isEmpty);

    await disposeApp(tester);
  });
}
