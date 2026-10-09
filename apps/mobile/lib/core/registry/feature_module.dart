import 'package:go_router/go_router.dart';

/// A self-contained slice of the app contributed by a features agent.
///
/// The router (`lib/core/router/app_router.dart`) plugs every module's
/// [branchRoutes] into the matching bottom-tab branch, adds its
/// [overlayRoutes] at the top level (above the shell), and `main.dart`
/// registers its [strings] with `AppStrings` at startup.
class FeatureModule {
  const FeatureModule({
    this.branchRoutes = const {},
    this.overlayRoutes = const [],
    this.strings = const {},
  });

  /// Routes inside bottom tabs. Keys: 'discover' | 'requests' | 'messages' | 'logistics'.
  /// The FIRST route in each list must be the tab root: '/discover', '/requests', '/messages', '/logistics'.
  final Map<String, List<RouteBase>> branchRoutes;

  /// Full-screen routes shown above the shell (top-level in GoRouter), e.g. '/listing/:id', '/chat/:id'.
  final List<RouteBase> overlayRoutes;

  /// {'ar': {'discover.title': 'استكشف'}, 'en': {'discover.title': 'Discover'}}
  final Map<String, Map<String, String>> strings;
}
