import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// Example questions shown as chips (i18n keys).
const List<String> kAssistantExampleKeys = [
  'discover.assistant.ex1',
  'discover.assistant.ex2',
  'discover.assistant.ex3',
];

/// Route that opens the assistant with [question] prefilled (not auto-sent).
String assistantRouteFor(String? question) {
  final q = question?.trim() ?? '';
  return q.isEmpty ? '/assistant' : '/assistant?q=${Uri.encodeQueryComponent(q)}';
}

/// Prominent "Ask the assistant" card for the Discover home, with example
/// questions and a visible feed entry.
class AssistantEntryCard extends StatelessWidget {
  const AssistantEntryCard({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg, AppSpacing.sm, AppSpacing.lg, AppSpacing.sm),
      child: Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              InkWell(
                key: const ValueKey<String>('assistant-entry'),
                onTap: () => context.push(assistantRouteFor(null)),
                child: Row(
                  children: [
                    const Icon(Icons.smart_toy_outlined),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Text(
                        context.tr('discover.assistant.ask'),
                        style: theme.textTheme.titleMedium
                            ?.copyWith(fontWeight: FontWeight.w800),
                      ),
                    ),
                    const Icon(Icons.chevron_right),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.xs,
                children: [
                  for (final k in kAssistantExampleKeys)
                    ActionChip(
                      key: ValueKey<String>('assistant-example-$k'),
                      label: Text(context.tr(k)),
                      onPressed: () =>
                          context.push(assistantRouteFor(context.tr(k))),
                    ),
                ],
              ),
              const SizedBox(height: AppSpacing.xs),
              Align(
                alignment: AlignmentDirectional.centerStart,
                child: TextButton.icon(
                  key: const ValueKey<String>('feed-entry-card'),
                  onPressed: () => context.push('/feed'),
                  icon: const Icon(Icons.dynamic_feed_outlined),
                  label: Text(context.tr('discover.open_feed')),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
