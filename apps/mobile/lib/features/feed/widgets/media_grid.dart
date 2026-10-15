import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/feed/feed_logic.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Up to five post images in a compact grid (1: wide, 2: halves, 3: one large
/// + two small, 4: 2x2, 5: 2 + 3).
class PostMediaGrid extends ConsumerWidget {
  const PostMediaGrid({super.key, required this.urls});

  final List<String> urls;

  static const double _gap = 3;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final shown = urls.where((u) => u.trim().isNotEmpty).take(5).toList();
    if (shown.isEmpty) return const SizedBox.shrink();
    final base = ref.watch(apiClientProvider).baseUrl;

    Widget tile(int i) => Semantics(
          image: true,
          label: context.tr('feed.image_n', {'n': '${i + 1}'}),
          child: SizedBox.expand(
            child: AppNetworkImage(
              url: postImageUrl(base, shown[i], width: 600),
              fit: BoxFit.cover,
            ),
          ),
        );

    Widget row(List<int> idx, double h) => SizedBox(
          height: h,
          child: Row(
            children: [
              for (var k = 0; k < idx.length; k++) ...[
                if (k > 0) const SizedBox(width: _gap),
                Expanded(child: tile(idx[k])),
              ],
            ],
          ),
        );

    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.sm),
      child: LayoutBuilder(
        key: const ValueKey<String>('feed-media-grid'),
        builder: (context, c) {
          final w = c.maxWidth.isFinite ? c.maxWidth : 320.0;
          switch (shown.length) {
            case 1:
              return SizedBox(height: w * 0.6, width: w, child: tile(0));
            case 2:
              return row(const [0, 1], w * 0.5);
            case 3:
              final h = w * 0.66;
              return SizedBox(
                height: h,
                child: Row(
                  children: [
                    Expanded(flex: 2, child: tile(0)),
                    const SizedBox(width: _gap),
                    Expanded(
                      child: Column(
                        children: [
                          Expanded(child: tile(1)),
                          const SizedBox(height: _gap),
                          Expanded(child: tile(2)),
                        ],
                      ),
                    ),
                  ],
                ),
              );
            case 4:
              return Column(
                children: [
                  row(const [0, 1], w * 0.36),
                  const SizedBox(height: _gap),
                  row(const [2, 3], w * 0.36),
                ],
              );
            default:
              return Column(
                children: [
                  row(const [0, 1], w * 0.4),
                  const SizedBox(height: _gap),
                  row(const [2, 3, 4], w * 0.27),
                ],
              );
          }
        },
      ),
    );
  }
}
