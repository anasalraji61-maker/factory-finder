import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/widgets/common_widgets.dart';
import 'package:flutter/material.dart';

/// Tidy placeholder for tabs that are not built yet.
class ComingSoonScreen extends StatelessWidget {
  const ComingSoonScreen({super.key, required this.titleKey, required this.icon});

  final String titleKey;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(context.tr(titleKey))),
      body: EmptyState(
        icon: icon,
        title: context.tr('common.coming_soon'),
        message: context.tr('common.coming_soon_msg'),
      ),
    );
  }
}
