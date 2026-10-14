import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/registry/feature_module.dart';
import 'package:factory_finder/features/module_a.dart';
import 'package:factory_finder/features/module_b.dart';
import 'package:factory_finder/features/module_c.dart';
import 'package:factory_finder/features/profile/profile_screen.dart';
import 'package:factory_finder/shell/app_shell.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

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

/// [showOnboarding] starts on the first-run flow (the real app does; tests
/// start on the shell).
GoRouter createAppRouter({bool showOnboarding = false}) {
  return GoRouter(
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
    errorBuilder: (context, state) => Scaffold(
      appBar: AppBar(),
      body: Center(child: Text(context.tr('common.error'))),
    ),
  );
}

final GoRouter appRouter = createAppRouter(showOnboarding: true);
