import 'package:factory_finder/core/api/api_client.dart' show kReleaseMockBuild;
import 'package:factory_finder/core/api/auth.dart' show sessionExpiredProvider;
import 'package:factory_finder/core/api/me_refresh.dart';
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

final _messengerKeyProvider =
    Provider<GlobalKey<ScaffoldMessengerState>>((ref) => GlobalKey<ScaffoldMessengerState>());

class FactoryFinderApp extends ConsumerWidget {
  const FactoryFinderApp({super.key, this.router, this.showMockBanner = kReleaseMockBuild});

  /// Release build running on mock data: paint a visible banner.
  final bool showMockBanner;

  /// Router override (tests pass a fresh one). Defaults to the app singleton.
  final GoRouter? router;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.watch(settingsPersistenceProvider);
    final locale = ref.watch(localeProvider);
    final themeMode = ref.watch(themeModeProvider);
    final digits = ref.watch(digitStyleProvider);
    final messengerKey = ref.watch(_messengerKeyProvider);
    ref.listen<bool>(sessionExpiredProvider, (_, expired) {
      if (!expired) return;
      ref.read(sessionExpiredProvider.notifier).state = false;
      messengerKey.currentState?.showSnackBar(SnackBar(
        key: const ValueKey<String>('session-expired-snack'),
        content: Text(AppStrings.lookup(locale.languageCode, 'auth.session_expired')),
      ));
    });
    return MaterialApp.router(
      debugShowCheckedModeBanner: false,
      scaffoldMessengerKey: messengerKey,
      onGenerateTitle: (context) => context.tr('app.name'),
      routerConfig: router ?? appRouter,
      locale: locale,
      supportedLocales: const [Locale('ar'), Locale('en')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      builder: (context, child) {
        final body = MeResumeRefresher(child: child ?? const SizedBox.shrink());
        return DigitStyleScope(
          style: digits,
          child: showMockBanner
              ? Banner(
                  key: const ValueKey<String>('mock-release-banner'),
                  message: 'MOCK DATA',
                  location: BannerLocation.topEnd,
                  child: body,
                )
              : body,
        );
      },
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: themeMode,
    );
  }
}
