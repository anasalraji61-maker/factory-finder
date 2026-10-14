import 'package:factory_finder/core/api/auth.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Fire-and-forget session restore (refresh + /v1/me); never throws.
void restoreSessionOnStart(ProviderContainer container) {
  container.read(authProvider.notifier).restore();
}
