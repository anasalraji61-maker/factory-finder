import 'dart:math' as math;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/offline.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:shimmer/shimmer.dart';

class AppCard extends StatelessWidget {
  const AppCard({
    super.key,
    required this.child,
    this.onTap,
    this.onLongPress,
    this.padding,
    this.semanticLabel,
    this.semanticActions,
  });

  final Widget child;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;
  final EdgeInsetsGeometry? padding;

  /// When set, screen readers announce exactly this label for the whole card
  /// (inner semantics are replaced). Expose inner actions through
  /// [semanticActions].
  final String? semanticLabel;
  final Map<CustomSemanticsAction, VoidCallback>? semanticActions;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final radius = BorderRadius.circular(AppRadius.md);
    final card = Material(
      color: scheme.surface,
      borderRadius: radius,
      child: InkWell(
        borderRadius: radius,
        onTap: onTap,
        onLongPress: onLongPress,
        child: Container(
          padding: padding ?? const EdgeInsets.all(AppSpacing.md),
          decoration: BoxDecoration(
            borderRadius: radius,
            border: Border.all(
              color: isDark ? const Color(0xFF26304D) : AppColors.border,
            ),
          ),
          child: child,
        ),
      ),
    );
    if (semanticLabel == null) return card;
    return Semantics(
      container: true,
      button: onTap != null,
      label: semanticLabel,
      onTap: onTap,
      customSemanticsActions: semanticActions,
      excludeSemantics: true,
      child: card,
    );
  }
}

class SectionHeader extends StatelessWidget {
  const SectionHeader({
    super.key,
    required this.title,
    this.actionLabel,
    this.onAction,
  });

  final String title;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Row(
        children: [
          Expanded(
            child: Text(
              title,
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.w800),
            ),
          ),
          if (actionLabel != null)
            TextButton(onPressed: onAction, child: Text(actionLabel!)),
        ],
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    this.message,
    this.action,
  });

  final IconData icon;
  final String title;
  final String? message;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 84,
              height: 84,
              decoration: BoxDecoration(
                color: theme.colorScheme.primary.withOpacity(0.12),
                shape: BoxShape.circle,
              ),
              child: Icon(icon, size: 40, color: theme.colorScheme.primary),
            ),
            const SizedBox(height: AppSpacing.lg),
            Text(
              title,
              textAlign: TextAlign.center,
              style: theme.textTheme.titleMedium
                  ?.copyWith(fontWeight: FontWeight.w800),
            ),
            if (message != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(
                message!,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: AppColors.secondaryOf(context)),
              ),
            ],
            if (action != null) ...[
              const SizedBox(height: AppSpacing.lg),
              action!,
            ],
          ],
        ),
      ),
    );
  }
}

class ErrorState extends StatelessWidget {
  const ErrorState({super.key, this.message, this.error, this.onRetry})
      : assert(message != null || error != null);

  /// Pre-rendered message. Ignored when [error] is a network failure.
  final String? message;

  /// Raw failure. Network errors (see [isNetworkError]) render the offline
  /// variant; anything else shows [describeError].
  final Object? error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final offline = error != null && isNetworkError(error!);
    final text = offline
        ? context.tr('offline.message')
        : (message ?? describeError(error!));
    return EmptyState(
      icon: offline ? Icons.wifi_off_rounded : Icons.cloud_off_rounded,
      title: context.tr(offline ? 'offline.title' : 'common.error'),
      message: text,
      action: onRetry == null
          ? null
          : OutlinedButton.icon(
              style: OutlinedButton.styleFrom(minimumSize: const Size(64, 48)),
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: Text(context.tr('common.retry')),
            ),
    );
  }
}

class LoadingList extends StatelessWidget {
  const LoadingList({super.key, this.itemCount = 6});

  final int itemCount;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Shimmer.fromColors(
      baseColor: isDark ? const Color(0xFF1E2744) : const Color(0xFFE5E9F2),
      highlightColor: isDark ? const Color(0xFF2B365A) : const Color(0xFFF6F8FC),
      child: ListView.separated(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.lg),
        itemCount: itemCount,
        separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
        itemBuilder: (_, __) => Row(
          children: [
            Container(
              width: 84,
              height: 84,
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(AppRadius.md),
              ),
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(height: 14, color: Colors.white),
                  const SizedBox(height: 10),
                  Container(height: 12, width: 140, color: Colors.white),
                  const SizedBox(height: 10),
                  Container(height: 12, width: 90, color: Colors.white),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Tests set this to true so no network/cache plugin is touched.
bool debugDisableNetworkImages = false;

class AppNetworkImage extends StatelessWidget {
  const AppNetworkImage({
    super.key,
    required this.url,
    this.width,
    this.height,
    this.fit = BoxFit.cover,
    this.borderRadius,
  });

  final String? url;
  final double? width;
  final double? height;
  final BoxFit fit;
  final BorderRadius? borderRadius;

  @override
  Widget build(BuildContext context) {
    final placeholder = Container(
      width: width,
      height: height,
      color: AppColors.border.withOpacity(0.6),
      alignment: Alignment.center,
      child: const Icon(Icons.image_outlined, color: AppColors.textSecondary),
    );
    final Widget image = (debugDisableNetworkImages || url == null || url!.isEmpty)
        ? placeholder
        : CachedNetworkImage(
            imageUrl: url!,
            width: width,
            height: height,
            fit: fit,
            // Decode at display size, not source size, so long feeds of
            // 12MP photos do not exhaust the image cache.
            memCacheWidth: (width != null && width!.isFinite)
                ? (width! * MediaQuery.of(context).devicePixelRatio).round()
                : 1080,
            placeholder: (context, _) => placeholder,
            errorWidget: (context, _, __) => placeholder,
          );
    if (borderRadius == null) return image;
    return ClipRRect(borderRadius: borderRadius!, child: image);
  }
}

class PrimaryButton extends StatelessWidget {
  const PrimaryButton({
    super.key,
    required this.label,
    this.onPressed,
    this.icon,
    this.loading = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    final style = FilledButton.styleFrom(
      minimumSize: const Size(64, 50),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
      ),
    );
    final Widget content = loading
        ? const SizedBox(
            width: 22,
            height: 22,
            child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
          )
        : Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (icon != null) ...[Icon(icon, size: 20), const SizedBox(width: 8)],
              Flexible(
                child: Text(label, style: const TextStyle(fontWeight: FontWeight.w800)),
              ),
            ],
          );
    return FilledButton(
      style: style,
      onPressed: loading ? null : onPressed,
      child: content,
    );
  }
}

class FilterChipBar extends StatelessWidget {
  const FilterChipBar({
    super.key,
    required this.labels,
    required this.selectedIndex,
    required this.onSelected,
  });

  final List<String> labels;
  final int selectedIndex;
  final ValueChanged<int> onSelected;

  @override
  Widget build(BuildContext context) {
    final scale = MediaQuery.textScalerOf(context).scale(14) / 14;
    return SizedBox(
      height: 48 * math.max(1.0, math.min(scale, 2.0)),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
        itemCount: labels.length,
        separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.sm),
        itemBuilder: (context, i) => ChoiceChip(
          label: Text(labels[i]),
          selected: i == selectedIndex,
          onSelected: (_) => onSelected(i),
        ),
      ),
    );
  }
}

class CountryFlag extends StatelessWidget {
  const CountryFlag({super.key, required this.countryCode, this.size = 18});

  final String countryCode;
  final double size;

  static String emoji(String code) {
    final c = code.toUpperCase();
    if (c.length != 2) return '🏳️';
    return String.fromCharCodes(c.codeUnits.map((u) => 0x1F1E6 + (u - 0x41)));
  }

  @override
  Widget build(BuildContext context) {
    return Text(emoji(countryCode), style: TextStyle(fontSize: size));
  }
}
