import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/providers.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:factory_finder/core/storage/persistence.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/utils/digits.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

class FactoryFinderApp extends ConsumerWidget {
  const FactoryFinderApp({super.key, this.router});

  /// Router override (tests pass a fresh one). Defaults to the app singleton.
  final GoRouter? router;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.watch(settingsPersistenceProvider);
    final locale = ref.watch(localeProvider);
    final themeMode = ref.watch(themeModeProvider);
    final digits = ref.watch(digitStyleProvider);
    return MaterialApp.router(
      debugShowCheckedModeBanner: false,
      onGenerateTitle: (context) => context.tr('app.name'),
      routerConfig: router ?? appRouter,
      locale: locale,
      supportedLocales: const [Locale('ar'), Locale('en')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      builder: (context, child) => DigitStyleScope(
        style: digits,
        child: child ?? const SizedBox.shrink(),
      ),
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: themeMode,
    );
  }
}
