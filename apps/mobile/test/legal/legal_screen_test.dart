import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/legal/legal_screen.dart';
import 'package:factory_finder/features/legal/legal_strings.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

Finder _k(String key) => find.byKey(ValueKey<String>(key));

Widget _app(Widget home, Locale locale) => MaterialApp(
      locale: locale,
      supportedLocales: const [Locale('ar'), Locale('en')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      home: home,
    );

void main() {
  setUpWidgetTests();
  setUpAll(() => AppStrings.register(legalStrings));

  testWidgets('shows draft banner, summary and copyable URL', (tester) async {
    String? clip;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData') {
          clip = (call.arguments as Map)['text'] as String?;
        }
        return null;
      },
    );
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));

    await tester.pumpWidget(_app(
      const LegalScreen(
          kind: LegalKind.privacy, url: 'https://example.test/privacy'),
      const Locale('en'),
    ));
    await settle(tester, frames: 2);
    expect(_k('legal-draft'), findsOneWidget);
    expect(find.text('Privacy Policy'), findsOneWidget);
    expect(_k('legal-url'), findsOneWidget);
    await tester.tap(_k('legal-copy-url'));
    await settle(tester, frames: 2);
    expect(clip, 'https://example.test/privacy');
    expect(_k('legal-url-copied'), findsOneWidget);
  });

  testWidgets('terms in Arabic without URL shows unavailable note',
      (tester) async {
    await tester.pumpWidget(_app(
      const LegalScreen(kind: LegalKind.terms, url: ''),
      const Locale('ar'),
    ));
    await settle(tester, frames: 2);
    expect(find.text('شروط الخدمة'), findsOneWidget);
    expect(_k('legal-url-missing'), findsOneWidget);
    expect(_k('legal-copy-url'), findsNothing);
  });

  testWidgets('every legal key exists in both languages', (tester) async {
    for (final lang in ['ar', 'en']) {
      expect(legalStrings[lang]!.keys.toSet(),
          legalStrings['en']!.keys.toSet());
    }
    for (final id in ['privacy', 'terms']) {
      for (var i = 1; i <= 5; i++) {
        expect(legalStrings['en']!.containsKey('legal.$id.p$i'), isTrue);
      }
    }
  });

  for (final c in const [
    ('settings-legal-privacy', '/legal/privacy'),
    ('settings-legal-terms', '/legal/terms'),
  ]) {
    testWidgets('Settings tile ${c.$1} opens ${c.$2}', (tester) async {
      final router = await pumpApp(tester, location: '/settings');
      final tile = _k(c.$1);
      await tester.dragUntilVisible(
          tile, find.byType(Scrollable).first, const Offset(0, -200));
      await tester.tap(tile);
      await settle(tester, frames: 3);
      expect(
          router.routerDelegate.currentConfiguration.uri.path, c.$2);
      await disposeApp(tester);
    });
  }
}
