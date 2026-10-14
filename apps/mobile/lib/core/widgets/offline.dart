import 'dart:async';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:flutter/material.dart';

/// True when [error] means "the server could not be reached" (offline, DNS,
/// connection refused, timeout). Connectivity-agnostic: it looks only at the
/// failure itself, never at the OS network state.
bool isNetworkError(Object error) {
  if (error is ApiException) {
    return error.status == null &&
        (error.code == 'network_error' || error.code == 'timeout');
  }
  return error is TimeoutException;
}

/// Compact banner with a retry button. Shown above a list when loading failed
/// because the network is unreachable.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key, required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      container: true,
      liveRegion: true,
      child: Material(
        key: const ValueKey('offline-banner'),
        color: scheme.errorContainer,
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.xs,
          ),
          child: Row(
            children: [
              Icon(Icons.wifi_off_rounded, size: 20, color: scheme.onErrorContainer),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Text(
                  context.tr('offline.banner'),
                  style: TextStyle(
                    color: scheme.onErrorContainer,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              TextButton(
                style: TextButton.styleFrom(
                  minimumSize: const Size(48, 48),
                  foregroundColor: scheme.onErrorContainer,
                ),
                onPressed: onRetry,
                child: Text(context.tr('common.retry')),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
