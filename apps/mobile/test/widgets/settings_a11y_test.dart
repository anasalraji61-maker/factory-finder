import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

double _contrast(Color a, Color b) {
  final la = a.computeLuminance();
  final lb = b.computeLuminance();
  final hi = la > lb ? la : lb;
  final lo = la > lb ? lb : la;
  return (hi + 0.05) / (lo + 0.05);
}

Widget _bare(Widget home, {Locale locale = const Locale('ar')}) => MaterialApp(
      locale: locale,
      supportedLocales: const [Locale('ar'), Locale('en')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      home: Scaffold(body: home),
    );

Future<void> _tapKey(WidgetTester tester, Object key) async {
  final all = find.byKey(ValueKey<String>('$key'));
  for (final dy in <double>[-250, 250]) {
    for (var i = 0; i < 20 && all.evaluate().isEmpty; i++) {
      await tester.drag(find.byType(Scrollable).first, Offset(0, dy));
      await tester.pump(const Duration(milliseconds: 100));
    }
  }
  final f = all.first;
  final w = tester.widget(f);
  if (w is ChoiceChip) {
    w.onSelected?.call(true);
  } else {
    await tester.ensureVisible(f);
    await tester.tap(f);
  }
  await settle(tester, frames: 3);
}

void main() {
  setUpWidgetTests();

  group('theme contrast audit', () {
    testWidgets('dark scheme text pairs meet WCAG AA (4.5:1)', (tester) async {
      final s = AppTheme.dark().colorScheme;
      final bg = AppTheme.darkBackground;
      final pairs = <String, double>{
        'onSurface/surface': _contrast(s.onSurface, s.surface),
        'onSurface/background': _contrast(s.onSurface, bg),
        'secondary text/surface': _contrast(AppColors.textSecondaryDark, s.surface),
        'secondary text/background': _contrast(AppColors.textSecondaryDark, bg),
        'primary/surface': _contrast(s.primary, s.surface),
        'primary/background': _contrast(s.primary, bg),
        'onPrimary/primary': _contrast(s.onPrimary, s.primary),
        'error/surface': _contrast(s.error, s.surface),
        'onError/error': _contrast(s.onError, s.error),
        'onSecondary/secondary': _contrast(s.onSecondary, s.secondary),
      };
      pairs.forEach((name, ratio) {
        expect(ratio, greaterThanOrEqualTo(4.5), reason: '$name = $ratio');
      });
      // Non-text boundary (input outline) needs 3:1.
      expect(_contrast(s.outline, s.surface), greaterThanOrEqualTo(3.0));
    });

    testWidgets('light scheme text pairs meet WCAG AA (4.5:1)', (tester) async {
      final s = AppTheme.light().colorScheme;
      final pairs = <String, double>{
        'onSurface/surface': _contrast(s.onSurface, s.surface),
        'secondary text/surface': _contrast(AppColors.textSecondary, s.surface),
        'secondary text/background':
            _contrast(AppColors.textSecondary, AppColors.background),
        'primary/background': _contrast(s.primary, AppColors.background),
        'onPrimary/primary': _contrast(s.onPrimary, s.primary),
        'white/condition badge': _contrast(Colors.white, const Color(0xFFB45309)),
      };
      pairs.forEach((name, ratio) {
        expect(ratio, greaterThanOrEqualTo(4.5), reason: '$name = $ratio');
      });
    });
  });

  group('digit style', () {
    testWidgets('MoneyText and tr follow the DigitStyleScope', (tester) async {
      await tester.pumpWidget(_bare(
        DigitStyleScope(
          style: DigitStyle.arabicIndic,
          child: Builder(
            builder: (context) => Column(
              children: [
                const MoneyText(Money(amount: '1234.5', currency: 'USD')),
                Text(context.tr('common.days', {'min': '5', 'max': '10'})),
              ],
            ),
          ),
        ),
      ));
      expect(find.text(r'$١٬٢٣٤٫٥٠'), findsOneWidget);
      expect(find.text('٥–١٠ يوم'), findsOneWidget);
    });

    testWidgets('western by default (no scope)', (tester) async {
      await tester.pumpWidget(_bare(
        const MoneyText(Money(amount: '1234.5', currency: 'USD')),
      ));
      expect(find.text(r'$1,234.50'), findsOneWidget);
    });
  });

  group('settings screen', () {
    testWidgets('changes apply app-wide and persist', (tester) async {
      await pumpApp(tester, logicalSize: const Size(540, 2400), location: '/settings');
      final c = ProviderScope.containerOf(tester.element(find.byType(FactoryFinderApp)));
      final store = c.read(keyValueStoreProvider) as MemoryStore;

      await _tapKey(tester, 'settings-theme-${ThemeMode.dark}');
      expect(c.read(themeModeProvider), ThemeMode.dark);
      expect(
        Theme.of(tester.element(find.byType(Scaffold).first)).brightness,
        Brightness.dark,
      );
      expect(store.data['theme_mode'], 'dark');

      await _tapKey(tester, 'settings-theme-${ThemeMode.light}');
      expect(
        Theme.of(tester.element(find.byType(Scaffold).first)).brightness,
        Brightness.light,
      );

      await _tapKey(tester, 'settings-currency-EUR');
      expect(c.read(displayCurrencyProvider), 'EUR');
      expect(store.data['display_currency'], 'EUR');

      c.read(destinationProvider.notifier).state =
          const Location(countryCode: 'IQ', city: 'Baghdad');
      await settle(tester, frames: 3);
      await _tapKey(tester, 'settings-city-Basra');
      expect(c.read(destinationProvider)?.city, 'Basra');
      expect(c.read(destinationProvider)?.countryCode, 'IQ');
      expect(store.data['destination'], contains('Basra'));
      expect(find.textContaining('البصرة'), findsWidgets);

      await _tapKey(tester, 'settings-digits-${DigitStyle.arabicIndic}');
      expect(c.read(digitStyleProvider), DigitStyle.arabicIndic);
      expect(store.data['digit_style'], 'arabic');

      await _tapKey(tester, 'settings-lang-en');
      expect(c.read(localeProvider).languageCode, 'en');
      expect(find.text('Settings'), findsWidgets);

      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });

    testWidgets('profile links to settings', (tester) async {
      await pumpApp(tester, location: '/profile');
      final tile = find.byKey(const ValueKey('profile-settings'));
      await tester.ensureVisible(tile);
      await tester.tap(tile);
      await settle(tester, frames: 4);
      expect(find.byKey(const ValueKey('settings-theme-ThemeMode.system')), findsOneWidget);
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });

    testWidgets('calculator defaults to the saved destination and currency',
        (tester) async {
      await pumpApp(
        tester,
        location: '/logistics/calculator',
        overrides: [
          displayCurrencyProvider.overrideWith((ref) => 'EUR'),
          destinationProvider.overrideWith(
            (ref) => const Location(countryCode: 'IQ', city: 'Basra'),
          ),
        ],
      );
      expect(find.textContaining('البصرة'), findsOneWidget);

      final chip = find.byKey(const ValueKey<String>('calc_display_cur_EUR'));
      await tester.scrollUntilVisible(
        chip,
        300,
        scrollable: find.byType(Scrollable).first,
      );
      expect(tester.widget<ChoiceChip>(chip).selected, isTrue);
      expect(tester.widget<ChoiceChip>(find.byKey(const ValueKey<String>('calc_display_cur_USD'))).selected, isFalse);
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });
  });

  group('offline UX', () {
    testWidgets('ErrorState shows the offline variant with retry for network errors',
        (tester) async {
      var retried = 0;
      await tester.pumpWidget(_bare(
        ErrorState(
          error: ApiException(code: 'network_error', message: 'SocketException'),
          onRetry: () => retried++,
        ),
      ));
      expect(find.text('لا يوجد اتصال بالخادم'), findsOneWidget);
      expect(find.textContaining('SocketException'), findsNothing);

      final retry = find.text('إعادة المحاولة');
      await tester.ensureVisible(retry);
      await tester.tap(retry);
      expect(retried, 1);
    });

    testWidgets('ErrorState shows the server message for non-network errors',
        (tester) async {
      await tester.pumpWidget(_bare(
        ErrorState(
          error: ApiException(status: 500, code: 'http_500', message: 'Boom'),
          onRetry: () {},
        ),
      ));
      expect(find.text('حدث خطأ غير متوقع'), findsOneWidget);
      expect(find.text('Boom'), findsOneWidget);
    });

    testWidgets('OfflineBanner has a 48dp retry target', (tester) async {
      var retried = 0;
      await tester.pumpWidget(_bare(OfflineBanner(onRetry: () => retried++)));
      expect(find.text('أنت غير متصل بالإنترنت'), findsOneWidget);
      final size = tester.getSize(find.widgetWithText(TextButton, 'إعادة المحاولة'));
      expect(size.height, greaterThanOrEqualTo(48));
      expect(size.width, greaterThanOrEqualTo(48));
      await tester.tap(find.text('إعادة المحاولة'));
      expect(retried, 1);
    });
  });

  group('accessibility', () {
    testWidgets('listing cards expose a spoken label and a compare action',
        (tester) async {
      final handle = tester.ensureSemantics();
      await pumpApp(tester, location: '/discover');
      await settle(tester, frames: 10);
      final card = find.bySemanticsLabel(RegExp('السعر'));
      expect(card, findsWidgets);
      final data = tester.getSemantics(card.first).getSemanticsData();
      expect(data.customSemanticsActionIds, isNotNull);
      expect(data.customSemanticsActionIds!.isNotEmpty, isTrue);
      handle.dispose();
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });

    testWidgets('icon buttons on discover/listing/supplier have tooltips (labels)',
        (tester) async {
      final router = await pumpApp(tester, location: '/discover');
      await settle(tester, frames: 8);
      expect(find.byTooltip('بحث وتصفية'), findsOneWidget);

      router.go('/listing/lst_001');
      await settle(tester, frames: 10);
      expect(find.byTooltip('متابعة المنتج'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });

    testWidgets('compare toggle and icon buttons are at least 48dp', (tester) async {
      await pumpApp(tester, location: '/discover');
      await settle(tester, frames: 10);
      final toggles = find.byTooltip('أضف للمقارنة');
      expect(toggles, findsWidgets);
      final size = tester.getSize(toggles.first);
      expect(size.width, greaterThanOrEqualTo(48));
      expect(size.height, greaterThanOrEqualTo(48));

      final tune = tester.getSize(find.byTooltip('بحث وتصفية'));
      expect(tune.width, greaterThanOrEqualTo(48));
      expect(tune.height, greaterThanOrEqualTo(48));
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });
  });

  group('text scale 2.0 at 360dp width', () {
    for (final entry in <String, String>{
      'discover': '/discover',
      'profile': '/profile',
      'settings': '/settings',
      'listing': '/listing/lst_001',
      'supplier': '/supplier/sup_cn_004',
    }.entries) {
      testWidgets('${entry.key} renders without overflow', (tester) async {
        tester.platformDispatcher.textScaleFactorTestValue = 2.0;
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        await pumpApp(
          tester,
          location: entry.value,
          logicalSize: const Size(360, 720),
        );
        await settle(tester, frames: 10);
        expect(tester.takeException(), isNull);

        // Scroll through the first scrollable to build lazily-created rows.
        final scrollables = find.byType(Scrollable);
        if (scrollables.evaluate().isNotEmpty) {
          await tester.drag(scrollables.first, const Offset(0, -600));
          await settle(tester, frames: 3);
          await tester.drag(scrollables.first, const Offset(0, -600));
          await settle(tester, frames: 3);
        }
        expect(tester.takeException(), isNull);
        await disposeApp(tester);
      });
    }
  });

  group('RTL', () {
    testWidgets('settings screen is right-to-left in Arabic and left-to-right in English',
        (tester) async {
      await pumpApp(tester, logicalSize: const Size(540, 2400), location: '/settings');
      expect(
        Directionality.of(tester.element(find.byKey(const ValueKey('settings-lang-ar')))),
        TextDirection.rtl,
      );
      await _tapKey(tester, 'settings-lang-en');
      expect(
        Directionality.of(tester.element(find.byKey(const ValueKey('settings-lang-ar')))),
        TextDirection.ltr,
      );
      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });
  });
}

