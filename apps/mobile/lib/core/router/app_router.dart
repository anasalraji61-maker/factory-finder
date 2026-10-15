import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/registry/feature_module.dart';
import 'package:factory_finder/core/router/auth_gate.dart';
import 'package:factory_finder/core/router/return_path.dart';
import 'package:factory_finder/features/module_a.dart';
import 'package:factory_finder/features/module_b.dart';
import 'package:factory_finder/features/module_c.dart';
import 'package:factory_finder/features/profile/profile_screen.dart';
import 'package:factory_finder/shell/app_shell.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

export 'package:factory_finder/core/router/return_path.dart' show sanitizeReturnPath;

final List<FeatureModule> featureModules = [featureModuleA, featureModuleB, featureModuleC];

/// Registers every module's i18n tables. Call once at startup.
void registerFeatureStrings() {
  for (final m in featureModules) {
    AppStrings.register(m.strings);
  }
}

List<RouteBase> _branch(String key) => <RouteBase>[
      for (final m in featureModules) ...(m.branchRoutes[key] ?? const <RouteBase>[]),
    ];

/// Screens that only make sense for a signed-in user. Matched on whole path
/// segments ('/deals' and '/deals/x', never '/dealsx'). Tab roots stay open
/// to guests (their screens show a sign-in prompt) so a tab tap never leaves
/// the user on a login page with nothing behind it.
const List<String> kProtectedPrefixes = <String>[
  '/deals',
  '/my-products',
  '/watchlist',
  '/alerts',
  '/notification-prefs',
  '/settings/change-password',
  '/settings/privacy',
  '/verification',
  '/supplier-claim',
  '/invoice',
  '/chat',
  '/messages/new',
  '/feed/new',
];

bool isProtectedPath(String path) {
  for (final p in kProtectedPrefixes) {
    if (path == p || path.startsWith('$p/')) return true;
  }
  return false;
}

/// Pure redirect rule (unit-tested). Returns the location to go to, or null
/// to stay. While the session restore is running nothing is redirected.
String? appRedirect({
  required Uri uri,
  required bool signedIn,
  required bool resolved,
}) {
  if (signedIn || !resolved) return null;
  if (!isProtectedPath(uri.path)) return null;
  final from = sanitizeReturnPath(uri.toString());
  if (from == null) return '/login';
  return Uri(path: '/login', queryParameters: {'from': from}).toString();
}

/// Localized 404 shown for unknown routes / deep links.
class NotFoundScreen extends StatelessWidget {
  const NotFoundScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('common.not_found.title'))),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.travel_explore, size: 64),
              const SizedBox(height: 16),
              Text(
                context.tr('common.not_found.title'),
                style: Theme.of(context).textTheme.titleLarge,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                context.tr('common.not_found.body'),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              FilledButton(
                key: const ValueKey<String>('not-found-home'),
                onPressed: () => context.go('/discover'),
                child: Text(context.tr('common.not_found.home')),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// [showOnboarding] starts on the first-run flow (the real app does; tests
/// start on the shell).
///
/// [auth] enables the protected-route redirect; without it (most widget
/// tests) no route is ever redirected.
GoRouter createAppRouter({bool showOnboarding = false, AuthGate? auth}) {
  return GoRouter(
    refreshListenable: auth?.refresh,
    redirect: auth == null
        ? null
        : (context, state) => appRedirect(
              uri: state.uri,
              signedIn: auth.isSignedIn(),
              resolved: auth.isResolved(),
            ),
    initialLocation: showOnboarding ? '/onboarding' : '/discover',
    routes: <RouteBase>[
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) =>
            AppShell(navigationShell: navigationShell),
        branches: <StatefulShellBranch>[
          StatefulShellBranch(routes: _branch('discover')),
          StatefulShellBranch(routes: _branch('requests')),
          StatefulShellBranch(routes: _branch('messages')),
          StatefulShellBranch(routes: _branch('logistics')),
          StatefulShellBranch(
            routes: <RouteBase>[
              GoRoute(
                path: '/profile',
                builder: (context, state) => const ProfileScreen(),
              ),
            ],
          ),
        ],
      ),
      for (final m in featureModules) ...m.overlayRoutes,
    ],
    errorBuilder: (context, state) => const NotFoundScreen(),
  );
}

/// Fallback singleton (no session gate); `main.dart` builds the real router.
final GoRouter appRouter = createAppRouter(showOnboarding: true);
