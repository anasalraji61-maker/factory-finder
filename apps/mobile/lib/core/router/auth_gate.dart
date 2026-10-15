import 'package:factory_finder/core/api/auth.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// What the router needs to know about the session, decoupled from Riverpod
/// so router tests can use a plain fake.
class AuthGate {
  const AuthGate({
    required this.isSignedIn,
    required this.isResolved,
    this.refresh,
  });

  /// True when a user is signed in.
  final bool Function() isSignedIn;

  /// False while the launch-time session restore is still running.
  final bool Function() isResolved;

  /// Fires when [isSignedIn] / [isResolved] change (feeds `refreshListenable`).
  final Listenable? refresh;

  /// Bridges the app's [ProviderContainer]. Lives as long as the app.
  factory AuthGate.fromContainer(ProviderContainer container) {
    final notifier = _AuthRefresh();
    container.listen<Me?>(authProvider, (_, __) => notifier.poke());
    container.listen<bool>(authResolvedProvider, (_, __) => notifier.poke());
    return AuthGate(
      isSignedIn: () => container.read(authProvider) != null,
      isResolved: () => container.read(authResolvedProvider),
      refresh: notifier,
    );
  }
}

class _AuthRefresh extends ChangeNotifier {
  void poke() => notifyListeners();
}
