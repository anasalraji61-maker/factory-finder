import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Public URL of the hosted privacy policy (`--dart-define=FF_PRIVACY_URL=...`).
const String kPrivacyUrl = String.fromEnvironment('FF_PRIVACY_URL');

/// Public URL of the hosted terms (`--dart-define=FF_TERMS_URL=...`).
const String kTermsUrl = String.fromEnvironment('FF_TERMS_URL');

enum LegalKind {
  privacy('privacy', kPrivacyUrl),
  terms('terms', kTermsUrl);

  const LegalKind(this.id, this.defaultUrl);
  final String id;
  final String defaultUrl;
}

/// Short in-app summary of a legal document plus its public URL as copyable
/// text. The summary is a DRAFT of `docs/legal/*.md`, not the legal text.
class LegalScreen extends StatefulWidget {
  /// [url] overrides the build-time URL (used by tests).
  const LegalScreen({super.key, required this.kind, this.url});

  final LegalKind kind;
  final String? url;

  @override
  State<LegalScreen> createState() => _LegalScreenState();
}

class _LegalScreenState extends State<LegalScreen> {
  bool _copied = false;

  Future<void> _copy(String url) async {
    await Clipboard.setData(ClipboardData(text: url));
    if (!mounted) return;
    setState(() => _copied = true);
  }

  @override
  Widget build(BuildContext context) {
    final id = widget.kind.id;
    final url = (widget.url ?? widget.kind.defaultUrl).trim();
    final secondary = AppColors.secondaryOf(context);
    return Scaffold(
      appBar: AppBar(title: Text(context.tr('legal.$id.title'))),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          AppCard(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Text(
              context.tr('legal.draft'),
              key: const ValueKey<String>('legal-draft'),
              style: const TextStyle(
                fontWeight: FontWeight.w700,
                color: AppColors.warning,
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          Text(
            context.tr('legal.summary_note'),
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: secondary),
          ),
          const SizedBox(height: AppSpacing.md),
          for (var i = 1; i <= 5; i++) ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Padding(
                  padding: EdgeInsets.only(top: 2),
                  child: Icon(Icons.circle, size: 6),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(child: Text(context.tr('legal.$id.p$i'))),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
          ],
          const SizedBox(height: AppSpacing.md),
          Semantics(
            header: true,
            child: Text(
              context.tr('legal.url.label'),
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          if (url.isEmpty)
            Text(
              context.tr('legal.url.unavailable'),
              key: const ValueKey<String>('legal-url-missing'),
              style: TextStyle(color: secondary),
            )
          else ...[
            Directionality(
              textDirection: TextDirection.ltr,
              child: SelectableText(
                url,
                key: const ValueKey<String>('legal-url'),
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: OutlinedButton.icon(
                key: const ValueKey<String>('legal-copy-url'),
                onPressed: () => _copy(url),
                icon: const Icon(Icons.copy_outlined),
                label: Text(context.tr('legal.url.copy')),
              ),
            ),
            if (_copied)
              Padding(
                padding: const EdgeInsets.only(top: AppSpacing.sm),
                child: Text(
                  context.tr('legal.url.copied'),
                  key: const ValueKey<String>('legal-url-copied'),
                  style: const TextStyle(color: AppColors.success),
                ),
              ),
          ],
        ],
      ),
    );
  }
}
