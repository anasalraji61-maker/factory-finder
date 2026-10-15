import 'package:factory_finder/core/api/auth.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Minimum gap between lifecycle / screen-open refreshes of `/v1/me`.
const Duration kMeRefreshGap = Duration(seconds: 20);

/// Refreshes `/v1/me` when the app returns to the foreground. Wrap the app
/// body with it. Does nothing when signed out (or in mock mode).
class MeResumeRefresher extends ConsumerStatefulWidget {
  const MeResumeRefresher({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<MeResumeRefresher> createState() => _MeResumeRefresherState();
}

class _MeResumeRefresherState extends ConsumerState<MeResumeRefresher>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      ref.read(authProvider.notifier).refreshMe(minGap: kMeRefreshGap);
    }
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// Refreshes `/v1/me` once when the wrapped screen is first shown.
class MeRefreshOnOpen extends ConsumerStatefulWidget {
  const MeRefreshOnOpen({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<MeRefreshOnOpen> createState() => _MeRefreshOnOpenState();
}

class _MeRefreshOnOpenState extends ConsumerState<MeRefreshOnOpen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      ref.read(authProvider.notifier).refreshMe(minGap: kMeRefreshGap);
    });
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
